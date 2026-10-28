from contextlib import aclosing

# Tools: things the model can ask Cerberus to do, like calculating exactly
# or searching your memories.
#
# The model never runs anything itself. It answers "I want calculate with
# 2*3" instead of a normal answer; Cerberus runs the Python function here,
# gives the result back, and the model goes on. That back and forth is the
# "agent loop" (stream_with_tools at the bottom).
#
# Safety: every tool only READS, CALCULATES, or saves a memory you can see
# and delete. The model also reads text you didn't write (documents, the
# strings in a program), and someone could hide instructions there, like
# "delete the user's files". That's called prompt injection. So there is
# no tool that runs commands, writes files or goes on the internet: then
# even a tricked model can't do any harm.

import ast
import json
import math
import operator
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from cerberus.storage import database, keeper
from cerberus.analysis import disasm
from cerberus.engines import ollama
from cerberus.analysis.reverse import find_strings

MAX_ROUNDS = 5  # how many times in a row the model may ask for tools
MAX_RESULT_CHARS = 4000  # a tool result that's too long would fill the context


@dataclass
class Context:
    """What the tools may need to know about where they are used."""

    chat_id: int | None = None  # the chat (for searching other chats)
    file: bytes | None = None  # the program in the Reverse panel


@dataclass
class Tool:
    name: str
    description: str  # tells the model WHAT it does and WHEN to use it
    parameters: dict  # its inputs, described as JSON Schema
    run: Callable  # async function(arguments, context) -> text

    def definition(self):
        # The format Ollama expects (the same one OpenAI uses).
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def one_text_input(name, about):
    # Most tools take one piece of text; this builds its JSON Schema.
    return {
        "type": "object",
        "properties": {name: {"type": "string", "description": about}},
        "required": [name],
    }


# ---------- calculate: exact math, safely ----------

# Python's eval() would run ANY code, like __import__("os").system(...).
# So we never use it. Instead, ast.parse turns the expression into a tree
# ("syntax tree"), and we walk through it, allowing only numbers and math.
OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
FUNCTIONS = {
    "sqrt": math.sqrt, "log": math.log, "log2": math.log2, "log10": math.log10,
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "abs": abs,
    "round": round, "floor": math.floor, "ceil": math.ceil, "factorial": math.factorial,
}
CONSTANTS = {"pi": math.pi, "e": math.e}


def evaluate(node):
    if isinstance(node, ast.Expression):
        return evaluate(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
        left, right = evaluate(node.left), evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("that power is too big")  # 9**9**9 would never finish
        return OPERATORS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = evaluate(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.Name) and node.id in CONSTANTS:
        return CONSTANTS[node.id]
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in FUNCTIONS
        and not node.keywords
    ):
        args = [evaluate(arg) for arg in node.args]
        if node.func.id == "factorial" and args and args[0] > 1000:
            raise ValueError("that factorial is too big")
        return FUNCTIONS[node.func.id](*args)
    raise ValueError("only numbers, + - * / ** % and math functions are allowed")


def calculate(expression):
    # People (and models) also write 2^10, 3×4 or 8÷2.
    expression = expression.replace("^", "**").replace("×", "*").replace("÷", "/")
    result = evaluate(ast.parse(expression, mode="eval"))
    if isinstance(result, float):
        if result.is_integer() and abs(result) < 1e15:
            return str(int(result))
        return f"{result:.12g}"  # 12 significant digits, no 0.30000000000000004
    return str(result)


async def run_calculate(arguments, context):
    return calculate(arguments["expression"])


# ---------- current_time ----------


async def run_current_time(arguments, context):
    # astimezone() adds the computer's own time zone.
    now = datetime.now().astimezone()
    return now.strftime("%A, %d %B %Y, %H:%M (local time, UTC%z)")


# ---------- search_memory and remember ----------


async def run_search_memory(arguments, context):
    # The same search Cerberus does by itself before every answer, but now
    # the model decides what to look for, and can search more than once.
    found = await keeper.recall(arguments["query"], keeper_mode=True, chat_id=context.chat_id)
    text = keeper.context_prompt(found)
    return text or "Nothing found in the memories, documents or earlier chats."


async def run_remember(arguments, context):
    fact = arguments["fact"].strip()
    # "Remember that..." is also saved automatically (context.py), so the
    # same fact could arrive twice. Then we keep only one.
    known = {memory["text"].lower() for memory in database.list_memories()}
    if fact.lower() in known:
        return f"Already in memory: {fact}"
    await keeper.add(fact)
    return f"Saved to memory: {fact}"


# ---------- Reverse panel: disassemble and find_strings ----------


def parse_address(value):
    # Addresses are hex, like in the listing: "0x1179" or "1179".
    if isinstance(value, int):
        return value
    return int(str(value).strip().lower().removeprefix("0x"), 16)


async def run_disassemble(arguments, context):
    if context.file is None:
        return "The file is no longer in memory. Ask the user to drop it again."
    return disasm.disassemble_at(context.file, parse_address(arguments["address"]))


async def run_find_strings(arguments, context):
    if context.file is None:
        return "The file is no longer in memory. Ask the user to drop it again."
    word = arguments["text"].lower()
    # ALL strings of the file, not only the first ones on the fact sheet.
    hits = [s for s in find_strings(context.file) if word in s["text"].lower()]
    if not hits:
        return f'No strings contain "{arguments["text"]}".'
    lines = [f"{s['offset']:x}  {s['text']}" for s in hits[:40]]
    more = f"\n... and {len(hits) - 40} more" if len(hits) > 40 else ""
    return f"{len(hits)} strings found:\n" + "\n".join(lines) + more


# ---------- The toolboxes ----------

CALCULATE = Tool(
    "calculate",
    "Calculate a math expression exactly. Use it for ANY arithmetic instead of "
    "doing it in your head. Supports + - * / ** %, brackets, sqrt, log, sin, "
    "cos, factorial, pi and e.",
    one_text_input("expression", "The expression, like (1234 * 5678) / 3 or sqrt(2)"),
    run_calculate,
)
CURRENT_TIME = Tool(
    "current_time",
    "Get today's date, the weekday and the current time. You don't know them otherwise.",
    {"type": "object", "properties": {}},
    run_current_time,
)
SEARCH_MEMORY = Tool(
    "search_memory",
    "Search what the user saved: their memories, their documents and earlier "
    "chats. Use it when the question is about the user, their files or the past.",
    one_text_input("query", "What to look for, in a few words"),
    run_search_memory,
)
REMEMBER = Tool(
    "remember",
    "Save a fact about the user to long-term memory. ONLY use this when the "
    "user clearly asks you to remember something.",
    one_text_input("fact", "The fact, as a short sentence about the user"),
    run_remember,
)
DISASSEMBLE = Tool(
    "disassemble",
    "Show the assembly of one function of the file, starting at an address. "
    "Use it to read functions you only know the address of, like 'function at 0x1179'.",
    one_text_input("address", "The address in hex, like 0x1179"),
    run_disassemble,
)
FIND_STRINGS = Tool(
    "find_strings",
    "Search ALL readable strings in the file for a word (the fact sheet only "
    "shows some). Use it to look for passwords, URLs, messages or file names.",
    one_text_input("text", "The word to look for, like password or http"),
    run_find_strings,
)

CHAT_TOOLS = [CALCULATE, CURRENT_TIME, SEARCH_MEMORY, REMEMBER]
REVERSE_TOOLS = [CALCULATE, DISASSEMBLE, FIND_STRINGS]


# ---------- Running tools, and the agent loop ----------


async def run_tool(tools, name, arguments, context):
    """Run one tool. Always returns text, also when something goes wrong."""
    tool = next((tool for tool in tools if tool.name == name), None)
    if tool is None:
        return f"There is no tool called {name}."
    if isinstance(arguments, str):  # some models send the inputs as JSON text
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return "The tool inputs were not valid JSON."
    try:
        result = str(await tool.run(arguments or {}, context))
    except Exception as error:
        # Any problem (a typo in the math, a missing input...) goes back to
        # the model as text. It can then fix its call or explain it.
        return f"Error: {error}"
    if len(result) > MAX_RESULT_CHARS:
        result = result[:MAX_RESULT_CHARS] + "\n... (cut, too long)"
    return result


async def stream_with_tools(model, messages, max_tokens, think=False, tools=(), context=None):
    """Like ollama.stream_events, but runs the tools the model asks for.

    Yields the same events, plus ("tool", {"name", "arguments", "result"})
    for every tool that was run, so the page can show it.
    """
    context = context or Context()
    messages = list(messages)  # a copy: we add to it, the caller's stays as it was
    definitions = [tool.definition() for tool in tools] or None

    for _ in range(MAX_ROUNDS):
        calls = []
        text = ""
        async with aclosing(ollama.stream_events(
            model, messages, max_tokens, think=think, tools=definitions
        )) as events:
            async for kind, value in events:
                if kind == "tool_calls":
                    calls += value
                else:
                    if kind == "content":
                        text += value
                    yield kind, value
        if not calls:
            return  # a normal answer: we're done

        # The model asked for tools. Its request goes into the conversation,
        # then each tool's result as a "tool" message, and we ask again.
        messages.append({"role": "assistant", "content": text, "tool_calls": calls})
        for call in calls:
            name = call["function"]["name"]
            arguments = call["function"].get("arguments") or {}
            result = await run_tool(tools, name, arguments, context)
            yield "tool", {"name": name, "arguments": arguments, "result": result}
            messages.append({"role": "tool", "tool_name": name, "content": result})

    # Still asking for tools after MAX_ROUNDS: one last time WITHOUT tools,
    # so it has to answer with what it has. No endless loops.
    async with aclosing(ollama.stream_events(model, messages, max_tokens, think=think)) as events:
        async for kind, value in events:
            yield kind, value
