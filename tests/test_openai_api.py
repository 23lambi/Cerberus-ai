# Tests for the other AI engines (cerberus/openai_api.py): the OpenAI-
# compatible connector, the engine switch in ollama.py, and API keys.
# The engine is faked with the kind of answers a real one sends.

import asyncio
import io
import json
import sqlite3
import stat
import zipfile

import httpx
import pytest

from cerberus import database, keys, ollama, openai_api

# The real functions, kept when this file loads: conftest's fake Ollama
# replaces them for each test, but some tests here need the real switch.
REAL_STREAM_EVENTS = ollama.stream_events
REAL_LIST_MODELS = ollama.list_models


def sse(*chunks):
    """A streamed answer as an engine sends it: "data: {...}" lines, then [DONE]."""
    lines = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks] + ["data: [DONE]\n\n"]
    return "".join(lines)


def delta(**fields):
    return {"choices": [{"index": 0, "delta": fields, "finish_reason": None}]}


def fake_engine(monkeypatch, handler, preset="custom", url="http://127.0.0.1:1234/v1"):
    """Choose a fake OpenAI-compatible engine; handler answers its requests."""
    database.set_setting("engine", "openai")
    database.set_setting("openai_preset", preset)
    database.set_setting("openai_url", url)
    requests = []

    def record(request):
        requests.append(request)
        return handler(request)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(openai_api.httpx, "AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(record)))
    return requests


def collect(model="m", messages=None, **kwargs):
    async def run():
        return [e async for e in ollama.stream_events(model, messages or [{"role": "user", "content": "hi"}], 100, **kwargs)]
    return asyncio.run(run())


# ---------- Which engine is on the internet ----------


@pytest.mark.parametrize("url, cloud", [
    ("https://router.huggingface.co/v1", True),
    ("https://api.openai.com/v1", True),
    ("http://127.0.0.1:1234/v1", False),
    ("http://localhost:8080/v1", False),
    ("http://192.168.1.20:1234/v1", False),  # a computer at home
    ("http://8.8.8.8/v1", True),
])
def test_cloud_or_local(url, cloud):
    assert openai_api.is_cloud(url) == cloud


# ---------- Translating messages ----------


def test_pictures_become_image_parts():
    sent = openai_api.to_openai([{"role": "user", "content": "What is this?", "images": ["aGVsbG8="]}])
    assert sent[0]["content"] == [
        {"type": "text", "text": "What is this?"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,aGVsbG8="}},
    ]


def test_tool_calls_get_ids_and_results_name_them():
    sent = openai_api.to_openai([
        {"role": "user", "content": "6*7 and the time?"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "calculate", "arguments": {"expression": "6*7"}}},
            {"function": {"name": "current_time", "arguments": {}}},
        ]},
        {"role": "tool", "tool_name": "calculate", "content": "42"},
        {"role": "tool", "tool_name": "current_time", "content": "Tuesday"},
    ])
    calls = sent[1]["tool_calls"]
    assert calls[0]["function"]["arguments"] == '{"expression": "6*7"}'  # JSON text, as OpenAI wants
    assert [m["tool_call_id"] for m in sent[2:]] == [calls[0]["id"], calls[1]["id"]]


# ---------- Streaming answers ----------


def test_an_answer_streams_with_thinking_and_token_counts(db, monkeypatch):
    def handler(request):
        return httpx.Response(200, text=sse(
            delta(role="assistant", reasoning_content="Let me think."),
            delta(content="Hello"), delta(content=" there"),
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 31, "completion_tokens": 4}},
        ))

    requests = fake_engine(monkeypatch, handler)
    events = collect()
    assert events[:3] == [("thinking", "Let me think."), ("content", "Hello"), ("content", " there")]
    stats = events[-1][1]
    assert events[-1][0] == "stats" and stats["tokens"] == 4 and stats["context"] == 35 and not stats["cut_off"]
    body = json.loads(requests[0].content)
    assert body["stream"] and body["max_tokens"] == 100


def test_a_tool_call_in_pieces_becomes_one_call(db, monkeypatch):
    # Engines may split the arguments over several lines.
    def handler(request):
        return httpx.Response(200, text=sse(
            delta(tool_calls=[{"index": 0, "id": "call_1", "type": "function",
                               "function": {"name": "calculate", "arguments": '{"expr'}}]),
            delta(tool_calls=[{"index": 0, "function": {"arguments": 'ession": "1234*5678"}'}}]),
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
        ))

    fake_engine(monkeypatch, handler)
    assert collect(tools=[{"type": "function"}]) == [
        ("tool_calls", [{"id": "call_1", "function": {"name": "calculate", "arguments": {"expression": "1234*5678"}}}]),
    ]


def test_an_answer_cut_at_the_limit_says_so(db, monkeypatch):
    fake_engine(monkeypatch, lambda request: httpx.Response(200, text=sse(
        delta(content="Long"), {"choices": [{"index": 0, "delta": {}, "finish_reason": "length"}]},
        {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 100}})))
    assert collect()[-1][1]["cut_off"] is True


def test_a_refused_key_is_explained(db, monkeypatch):
    fake_engine(monkeypatch, lambda request: httpx.Response(401, json={"error": {"message": "bad key"}}),
                preset="openai", url="")
    with pytest.raises(ollama.OllamaError, match="refused the API key"):
        collect()


def test_an_engine_that_is_not_running_is_explained(db, monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("refused")

    fake_engine(monkeypatch, refuse, preset="lmstudio", url="")
    with pytest.raises(ollama.OllamaError, match="LM Studio can't be reached"):
        collect()


def test_the_engine_error_message_is_passed_on(db, monkeypatch):
    fake_engine(monkeypatch, lambda request: httpx.Response(404, json={"error": "model 'x' not found"}))
    with pytest.raises(ollama.OllamaError, match="model 'x' not found"):
        collect()


def test_the_key_goes_in_the_authorization_header(db, monkeypatch):
    keys.set("openai_key", "hf_secret")
    requests = fake_engine(monkeypatch, lambda request: httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}]}),
                           preset="huggingface", url="")
    assert asyncio.run(ollama.list_models()) == ["a", "b"]
    assert requests[0].headers["authorization"] == "Bearer hf_secret"
    assert str(requests[0].url) == "https://router.huggingface.co/v1/models"  # the preset's own address


# ---------- The whole app with another engine ----------


def test_chat_uses_the_chosen_engine_and_the_page_knows_it_is_cloud(client, monkeypatch):
    # conftest gives the page a fake Ollama; here the real switch must answer.
    from cerberus.routes import pages
    monkeypatch.setattr(pages, "list_models", REAL_LIST_MODELS)
    monkeypatch.setattr(ollama, "stream_events", REAL_STREAM_EVENTS)
    fake_engine(monkeypatch, lambda request: (
        httpx.Response(200, json={"data": [{"id": "Qwen/Qwen2.5-7B-Instruct"}]}) if request.url.path.endswith("/models")
        else httpx.Response(200, text=sse(delta(content="Hi from the cloud"),
                                         {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 3}}))
    ), preset="huggingface", url="")
    models = client.get("/models").json()
    assert models["models"] == ["Qwen/Qwen2.5-7B-Instruct"]
    assert models["engine"] == {"kind": "openai", "name": "Hugging Face (cloud)", "cloud": True}
    response = client.post("/chat", json={"model": "Qwen/Qwen2.5-7B-Instruct",
                                         "messages": [{"role": "user", "content": "hello there friend"}]})
    text = "".join(json.loads(line).get("text", "") for line in response.text.splitlines())
    assert "Hi from the cloud" in text


def test_choosing_an_engine_saves_and_tests_it(client, monkeypatch):
    fake_engine(monkeypatch, lambda request: httpx.Response(200, json={"data": [{"id": "llama"}]}))
    answer = client.post("/setup/engine", json={"engine": "openai", "preset": "lmstudio",
                                                "url": "http://127.0.0.1:1234/v1", "key": ""}).json()
    assert answer == {"ok": True, "models": 1}
    assert database.get_setting("openai_url") == ""  # the preset's own address: it follows the preset
    assert client.post("/setup/engine", json={"engine": "ollama"}).json()["ok"] in (True, False)
    assert database.get_setting("engine") == "ollama"


def test_bad_engine_choices_are_refused(client):
    assert client.post("/setup/engine", json={"engine": "skynet"}).status_code == 422
    assert client.post("/setup/engine", json={"engine": "openai", "preset": "nope"}).status_code == 422
    assert client.post("/setup/engine", json={"engine": "openai", "preset": "custom",
                                              "url": "file:///etc/passwd"}).status_code == 422


# ---------- API keys stay secret ----------


def test_a_key_is_stored_privately_and_never_sent_back(client, monkeypatch):
    fake_engine(monkeypatch, lambda request: httpx.Response(200, json={"data": []}), preset="openai", url="")
    client.post("/setup/engine", json={"engine": "openai", "preset": "openai", "key": "sk-very-secret"})

    assert keys.get("openai_key") == "sk-very-secret"
    assert stat.S_IMODE(keys.KEYS_FILE.stat().st_mode) == 0o600  # only you may read it
    for url in ("/settings", "/setup/engines", "/setup/status"):
        assert "sk-very-secret" not in client.get(url).text
    assert client.get("/settings").json()["openai_key_set"] == "yes"
    with database.get_db() as conn:
        assert "sk-very-secret" not in str(conn.execute("SELECT * FROM settings").fetchall())
    with zipfile.ZipFile(io.BytesIO(client.get("/backup").content)) as archive:
        assert b"sk-very-secret" not in archive.read("cerberus.db")


def test_an_empty_key_keeps_the_saved_one_and_reset_removes_it(client):
    keys.set("openai_key", "sk-keep")
    client.put("/settings", json={"openai_key": ""})
    assert keys.get("openai_key") == "sk-keep"
    client.post("/settings/reset")
    assert keys.get("openai_key") == ""
