# Tests for the tools and the agent loop. The fake Ollama plays a script:
# first it asks for a tool, then it answers, like a real model would.

import asyncio
import json
from pathlib import Path

import pytest

from cerberus.storage import database
from cerberus.chat import tools
from cerberus.routes.reverse import recent_files

FILES = Path(__file__).parent / "fixtures"


def ask_tool(name, **arguments):
    # One answer from the fake model: "please run this tool".
    return [("tool_calls", [{"function": {"name": name, "arguments": arguments}}])]


def answer(text):
    return [("content", text)]


def events(response):
    return [json.loads(line) for line in response.text.splitlines()]


def chat_body(text, model="tooly:7b", chat_id=None):
    return {"model": model, "chat_id": chat_id, "tools": True,
            "messages": [{"role": "user", "content": text}]}


# ---------- calculate ----------


@pytest.mark.parametrize(
    "expression, result",
    [
        ("1234 * 5678", "7006652"),
        ("2^10", "1024"),  # ^ is understood as "to the power of"
        ("(1 + 2) * 3 / 4", "2.25"),
        ("1 / 3", "0.333333333333"),
        ("sqrt(16) + factorial(3)", "10"),
        ("-5 % 3", "1"),
    ],
)
def test_calculate(expression, result):
    assert tools.calculate(expression) == result


@pytest.mark.parametrize(
    "dangerous",
    [
        "__import__('os').system('rm -rf ~')",  # code, not math
        "open('/etc/passwd').read()",
        "(lambda: 1)()",
        "9 ** 9 ** 9",  # would run for ages and eat all the RAM
    ],
)
def test_calculate_refuses_everything_but_math(dangerous):
    with pytest.raises(ValueError):
        tools.calculate(dangerous)


def test_current_time_has_the_year():
    text = asyncio.run(tools.run_current_time({}, tools.Context()))
    assert "20" in text and ":" in text


# ---------- the agent loop ----------


def test_the_model_uses_a_tool_and_then_answers(client, fake):
    fake.script = [ask_tool("calculate", expression="1234*5678"), answer("It's 7,006,652.")]

    response = client.post("/chat", json=chat_body("What is 1234 * 5678?"))

    kinds = [event["type"] for event in events(response)]
    assert kinds == ["stats", "tool", "content", "stats", "done"]
    tool = events(response)[1]
    assert tool["name"] == "calculate" and tool["result"] == "7006652"
    # The second time, the model gets its own request and the tool's result.
    second = fake.calls[-1]["messages"]
    assert second[-2]["tool_calls"][0]["function"]["name"] == "calculate"
    assert second[-1] == {"role": "tool", "tool_name": "calculate", "content": "7006652"}


def test_tool_errors_go_back_to_the_model(client, fake):
    fake.script = [ask_tool("calculate", expression="2 +* 3"), answer("Sorry.")]
    tool = [e for e in events(client.post("/chat", json=chat_body("2+*3?"))) if e["type"] == "tool"][0]
    assert tool["result"].startswith("Error:")


def test_unknown_tools_are_refused(client, fake):
    fake.script = [ask_tool("run_shell", command="rm -rf /"), answer("I can't.")]
    tool = [e for e in events(client.post("/chat", json=chat_body("hi there friend"))) if e["type"] == "tool"][0]
    assert tool["result"] == "There is no tool called run_shell."


def test_the_loop_stops_after_max_rounds(client, fake):
    # A confused model that asks for a tool forever.
    fake.script = [ask_tool("current_time")] * 10 + [answer("Done.")]
    client.post("/chat", json=chat_body("What time is it now?"))

    tool_calls = [call for call in fake.calls if call["model"] == "tooly:7b"]
    assert len(tool_calls) == tools.MAX_ROUNDS + 1
    assert tool_calls[-1]["tools"] is None  # the last try has no tools: it must answer


def test_no_tools_for_models_that_cant_use_them(client, fake):
    client.post("/chat", json=chat_body("hello there friend", model="small:3b"))
    assert fake.calls[-1]["tools"] is None


def test_only_the_answer_is_saved(client, fake):
    chat_id = client.post("/chats", json={}).json()["id"]
    fake.script = [ask_tool("calculate", expression="6*7"), answer("42.")]
    client.post("/chat", json=chat_body("What is 6*7?", chat_id=chat_id))
    saved = [m["content"] for m in database.get_chat(chat_id)["messages"]]
    assert saved == ["What is 6*7?", "42."]


# ---------- memory tools ----------


def test_search_memory(db, fake):
    # fake: no real Ollama, so the search matches words (of 4+ letters).
    database.add_memory("The user's dog is called Rex", None)
    result = asyncio.run(tools.run_search_memory({"query": "how is my dog called"}, tools.Context()))
    assert "Rex" in result


def test_remember_saves_once(db, fake):
    for _ in range(2):  # the same fact twice
        asyncio.run(tools.run_remember({"fact": "I like tea"}, tools.Context()))
    assert [m["text"] for m in database.list_memories()] == ["I like tea"]


# ---------- Reverse tools ----------


def test_disassemble_any_function(client, fake):
    facts = client.post("/reverse?name=crackme2", content=(FILES / "crackme2").read_bytes()).json()
    fake.script = [ask_tool("disassemble", address="0x1179"), answer("The password is dog!")]

    response = client.post("/reverse/chat", json={
        "model": "tooly:7b", "facts": facts, "tools": True,
        "messages": [{"role": "user", "content": "What does 0x1179 check?"}],
    })

    tool = [e for e in events(response) if e["type"] == "tool"][0]
    assert "; 'd'" in tool["result"] and "; '!'" in tool["result"]


def test_find_strings_searches_the_whole_file():
    context = tools.Context(file=(FILES / "crackme").read_bytes())
    result = asyncio.run(tools.run_find_strings({"text": "PASSWORD"}, context))
    assert "Enter password:" in result and "Wrong password." in result


def test_reverse_tools_need_the_file():
    result = asyncio.run(tools.run_disassemble({"address": "0x1179"}, tools.Context()))
    assert "drop it again" in result


def test_only_a_few_files_are_kept_in_memory(client):
    for number in range(5):
        client.post(f"/reverse?name=f{number}", content=b"file number %d" % number)
    assert len(recent_files) == 3


# ---------- Tool calls written as text ----------

def test_a_tool_call_written_as_text_is_run(client, fake):
    # qwen2.5-coder answers with the call as its message instead of asking.
    fake.script = [answer('{"name": "calculate", "arguments": {"expression": "1234*5678"}}'),
                   answer("It's 7,006,652.")]
    found = events(client.post("/chat", json=chat_body("What is 1234 * 5678?")))
    assert [e["type"] for e in found] == ["stats", "tool", "content", "stats", "done"]
    assert found[1]["result"] == "7006652"
    assert "".join(e["text"] for e in found if e["type"] == "content") == "It's 7,006,652."


@pytest.mark.parametrize("text", [
    '{"color": "red", "size": 3}',  # JSON the user asked for
    '{"name": "Ada", "arguments": "none"}',  # looks close, but no call
    "`code` is a word in backticks",
])
def test_other_answers_that_look_like_json_are_shown_unchanged(client, fake, text):
    fake.script = [answer(text)]
    found = events(client.post("/chat", json=chat_body("Show me")))
    assert [e["type"] for e in found] == ["content", "stats", "done"]
    assert found[0]["text"] == text


CALC = {"expression": "2*3"}


@pytest.mark.parametrize("text,names", [
    # Every common way models write calls as text:
    ('{"name": "calculate", "arguments": {"expression": "2*3"}}', ["calculate"]),
    ('{"name": "calculate", "parameters": {"expression": "2*3"}}', ["calculate"]),  # llama3.2
    ('{"name": "calculate", "arguments": "{\\"expression\\": \\"2*3\\"}"}', ["calculate"]),
    ('{"type": "function", "function": {"name": "calculate", "arguments": {"expression": "2*3"}}}', ["calculate"]),
    ('[TOOL_CALLS] [{"name": "calculate", "arguments": {"expression": "2*3"}}]', ["calculate"]),  # Mistral
    ('[TOOL_CALLS][{"name": "calculate", "arguments": {}}, {"name": "current_time", "arguments": {}}]',
     ["calculate", "current_time"]),
    ('<|python_tag|>{"name": "calculate", "parameters": {"expression": "2*3"}}', ["calculate"]),  # Llama 3.1
    ('<tool_call>\n{"name": "calculate", "arguments": {}}\n</tool_call>\n'
     '<tool_call>\n{"name": "current_time", "arguments": {}}\n</tool_call>', ["calculate", "current_time"]),  # Qwen
    ('<function=calculate>{"expression": "2*3"}</function>', ["calculate"]),
    ('```json\n{"name": "calculate", "arguments": {"expression": "2*3"}}\n```', ["calculate"]),
    ('{"name": "calculate", "parameters": {"expression": "2*3"}}\n\nThis computes it.', ["calculate"]),
    # Calls to tools that don't exist, and garbled calls llama3.2 really wrote:
    ('{"name": "print", "parameters": {"expression": "hi"}}', tools.UNKNOWN_TOOL),
    ('{"name":"calculate","parameters{"expression":"15% * 240"}}', tools.UNKNOWN_TOOL),
    ('{"name":"calculate","parameters":{"expression":"["\\"Rain\\"","\\"drops', tools.UNKNOWN_TOOL),
    # Normal answers:
    ('{"color": "red", "size": 3}', None),
    ('{"name": "Ada", "age": 36}', None),
    ('[1, 2, 3]', None),
    ('[Python](https://python.org) is a language.', None),
])
def test_written_tool_calls_in_every_common_format(text, names):
    found = tools.calls_written_as_text(text, tools.CHAT_TOOLS)
    assert ([call["function"]["name"] for call in found] if isinstance(found, list) else found) == names


@pytest.mark.parametrize("start,waits", [
    ('{"name": "calc', True),
    ("[TOOL_CALLS]", True),
    ("[Python](https://python.org) is a lovely language", False),
    ("<b>Bold</b> statement here, long enough to tell for sure", False),
    ("Hello", False),
])
def test_only_answers_that_may_be_calls_wait(start, waits):
    assert tools.might_be_call(start) is waits


def test_markdown_answers_still_stream(client, fake):
    fake.script = [[("content", "[Python](https://python.org) "), ("content", "is a language for "),
                    ("content", "beginners and experts alike."), ("content", " Try it.")]]
    found = events(client.post("/chat", json=chat_body("Link?")))
    assert [e["type"] for e in found] == ["content"] * 4 + ["stats", "done"]


def test_a_made_up_tool_gets_a_normal_answer_instead(client, fake):
    # llama3.2 asked to say hello "calls" a print tool that doesn't exist.
    fake.script = [answer('{"name": "print", "parameters": {"expression": "Hello there"}}'),
                   answer("Hello there, nice to meet you!")]
    found = events(client.post("/chat", json=chat_body("Say hello in five words.")))
    assert "".join(e["text"] for e in found if e["type"] == "content") == "Hello there, nice to meet you!"
    assert not any(e["type"] == "tool" for e in found)
    assert fake.calls[-1]["tools"] is None  # asked again without tools


# ---------- Models that always think ----------

def test_a_model_that_always_thinks_keeps_its_reasoning_apart(client, fake, monkeypatch):
    from cerberus.engines import ollama
    async def always(model):
        return ["completion", "thinking", "always-thinking"]
    monkeypatch.setattr(ollama, "capabilities", always)
    client.post("/chat", json={"model": "qwen3:4b", "messages": [{"role": "user", "content": "Hi"}]})
    assert fake.calls[-1]["think"] is True  # even with the Think switch off


def test_a_model_that_can_stop_thinking_is_not_slowed_down(client, fake, monkeypatch):
    from cerberus.engines import ollama
    async def can_switch(model):
        return ["completion", "thinking"]
    monkeypatch.setattr(ollama, "capabilities", can_switch)
    client.post("/chat", json={"model": "deepseek-r1:8b", "messages": [{"role": "user", "content": "Hi"}]})
    assert fake.calls[-1]["think"] is False
