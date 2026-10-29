"""Does every installed model give clean answers in Cerberus?

  venv/bin/python scripts/check_models.py              all installed chat models
  venv/bin/python scripts/check_models.py --model qwen3:4b --runs 3 --show

Users can pick any model, and models differ: some think even when told not
to, some write tool calls as text in their own format. This runs each model
through Cerberus's own answer pipeline (the thinking filter, the tool loop)
with the AI engine chosen in Settings, and checks what a user would see:

  plain answer   Think off: no reasoning ("Okay, the user is asking...") in it
  tools          the calculator really runs: 1234 * 5678 = 7,006,652
  tools on       an everyday question with Tools on: no raw tool call shown

✓ clean · ~ works, but not as intended (answered without the tool) · ✗ broken.
Each model is unloaded after its checks. Models bigger than half of this
computer's memory are skipped (loading one can make the system stop Ollama),
unless you name them with --model.
Exit code 1 when anything is broken. A new ✗ usually means a model writes
reasoning or tool calls in a way Cerberus doesn't read yet: see --show.
"""
import argparse
import asyncio
import re
import sys
from contextlib import aclosing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cerberus.chat import tools  # noqa: E402
from cerberus.chat.prompts import SYSTEM_PROMPT  # noqa: E402
from cerberus.core.setup import total_ram_gb  # noqa: E402
from cerberus.core.config import DEFAULT_MAX_TOKENS, THINK_MAX_TOKENS  # noqa: E402
from cerberus.engines import ollama  # noqa: E402

# What a user should never see in an answer.
REASONING = re.compile(
    r"^\s*(okay|ok|alright|hmm|so,? the user|let me|first,? i|we need to|the user (is asking|wants|asked))\b"
    r"|</?(think|thinking|reasoning)>", re.I)
RAW_CALL = re.compile(r'"(name|function)"\s*:|\[TOOL_CALLS\]|<tool_call>|<\|python_tag\|>|<function=', re.I)


async def answer(model, question, use_tools):
    """What the user would see: (answer text, tools run, reasoning kept apart)."""
    think = await ollama.should_think(model, False)
    messages = [{"role": "system", "content": SYSTEM_PROMPT.strip()}, {"role": "user", "content": question}]
    toolbox = tools.CHAT_TOOLS if use_tools else []
    text, used, thought = "", [], False
    max_tokens = DEFAULT_MAX_TOKENS + (THINK_MAX_TOKENS if think else 0)
    async with aclosing(tools.stream_with_tools(model, messages, max_tokens, think, toolbox)) as events:
        async for kind, value in events:
            if kind == "content":
                text += value
            elif kind == "tool":
                used.append(value["name"])
            elif kind == "thinking":
                thought = True
    return text.strip(), used, thought


def judge(check, text, used):
    """✓, ~ or ✗, and why."""
    if not text:
        return "✗", "empty answer"
    if REASONING.search(text):
        return "✗", "reasoning in the answer"
    if RAW_CALL.search(text):
        return "✗", "raw tool call shown"
    if check == "tools":
        if "7006652" not in text.replace(",", "").replace(".", "").replace(" ", ""):
            return "✗", "wrong result"
        if "calculate" not in used:
            return "~", "right result, without the calculator"
    return "✓", ""


CHECKS = [
    ("plain answer", "What is the capital of France? One sentence.", False),
    ("tools", "Use the calculator to compute 1234 * 5678.", True),
    ("tools on", "Say hello in five words.", True),
]


async def check_model(model, runs, show):
    can_tools = await ollama.can_use_tools(model)
    row = {}
    for name, question, use_tools in CHECKS:
        if use_tools and not can_tools:
            row[name] = ("-", "no tools")
            continue
        results = []
        for _ in range(runs):
            try:
                text, used, thought = await answer(model, question, use_tools)
                mark, why = judge(name, text, used)
            except ollama.OllamaError as error:
                text, mark, why = "", "✗", f"error: {error}"
            results.append((mark, why))
            if show or mark == "✗":
                print(f"    {model} · {name}: {mark} {why} · {' '.join(text.split())[:150]!r}")
        worst = next((r for mark in "✗~✓" for r in results if r[0] == mark), results[0])
        bad = sum(r[0] == "✗" for r in results)
        row[name] = (worst[0] + (f" {bad}/{runs}" if bad else ""), worst[1])
    return row


async def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--model", action="append", help="check only this model (repeatable)")
    parser.add_argument("--runs", type=int, default=2, help="answers per check (default 2)")
    parser.add_argument("--show", action="store_true", help="print every answer")
    args = parser.parse_args()
    try:
        models = args.model or [name for name in await ollama.list_models() if await ollama.can_chat(name)]
        local = ollama.engine() == "ollama"
        sizes = {m["name"]: m["size"] / 1024**3 for m in await ollama.installed()} if local else {}
    except ollama.OllamaError as error:
        raise SystemExit(f"The AI engine is not reachable: {error}") from None
    ram = total_ram_gb()
    if ram and not args.model:
        too_big = [name for name in models if sizes.get(name, 0) > 0.5 * ram]
        for name in too_big:
            print(f"Skipping {name}: {sizes[name]:.0f} GB is too big for {ram:.0f} GB of memory. Use --model {name} to check it anyway.")
        models = [name for name in models if name not in too_big]
    print(f"Checking {len(models)} models, {args.runs} answers per check. This takes a while.\n")
    rows = {}
    for model in models:
        print(f"  {model}…")
        rows[model] = await check_model(model, args.runs, args.show)
        if local:
            await ollama.unload(model)  # Ollama keeps models in memory for 30 minutes
    width = max(len(model) for model in models)
    print("\n" + "Model".ljust(width) + "".join(f"  {name:<16}" for name, _, _ in CHECKS) + "  Notes")
    broken = False
    for model, row in rows.items():
        notes = sorted({why for _, why in row.values() if why and why != "no tools"})
        broken |= any(mark.startswith("✗") for mark, _ in row.values())
        print(model.ljust(width) + "".join(f"  {row[name][0]:<16}" for name, _, _ in CHECKS) + "  " + "; ".join(notes))
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
