# conftest.py is a special file: pytest loads it before the tests, and the
# fixtures in it can be used by every test file in this folder.
#
# A fixture is a function that prepares something a test needs. A test asks
# for it by having a parameter with the same name: def test_x(db): ...
# pytest sees "db", runs the db fixture, and passes in what it returns.

import pytest
from fastapi.testclient import TestClient

from cerberus.storage import database, keeper
from cerberus.core import settings
from cerberus.engines import ollama
from cerberus.engines.ollama import OllamaError
from cerberus.routes import pages


@pytest.fixture(autouse=True)
def private_keys(tmp_path, monkeypatch):
    # autouse: every test gets this, without asking for it. API keys then
    # go to a temporary file, never to the real one on your computer.
    from cerberus.storage import keys
    monkeypatch.setattr(keys, "KEYS_FILE", tmp_path / "keys.json")


@pytest.fixture(autouse=True)
def no_real_docker(monkeypatch):
    # The SearXNG switch can start and stop a Docker container. In tests
    # Docker is never really asked: a test that needs it fakes its answers.
    from cerberus.search import searxng

    def refuse(*args):
        raise OSError("no real docker in tests")

    monkeypatch.setattr(searxng, "run_docker", refuse)


@pytest.fixture
def db(tmp_path, monkeypatch):
    # tmp_path is a fixture built into pytest: a new, empty folder for
    # every test. So each test gets its own fresh database, and the real
    # cerberus.db is never touched.
    # monkeypatch changes a value only while the test runs, then puts the
    # old value back by itself.
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()


class FakeOllama:
    """Pretends to be Ollama: answers instantly and writes down every call.

    Replacing a slow or outside part with a fake like this is called mocking.
    The tests then run in milliseconds, without Ollama, and always give the
    same result.
    """

    MODELS = ["small:3b", "big:8b", "thinker:4b", "eyes:4b", "tooly:7b", "embed-text"]

    def __init__(self):
        self.calls = []  # every request the "model" got
        self.reply = "Hello from the fake model"
        self.loaded = []  # the models "in RAM"
        self.unloaded = []  # every model we were asked to unload
        # A script for the next answers: each item is one answer, as a list
        # of events, like [("tool_calls", [...])]. Empty = the normal reply.
        self.script = []

    async def stream_events(
        self, model, messages, max_tokens=600, temperature=None, think=False, tools=None
    ):
        # list(messages): a copy, because the agent loop keeps adding to its list.
        self.calls.append({"model": model, "messages": list(messages), "think": think, "tools": tools})
        if self.script:
            for event in self.script.pop(0):
                yield event
            yield "stats", {"tokens": 5, "seconds": 0.5, "context": 50, "num_ctx": 8192, "cut_off": False}
            return
        if think:
            yield "thinking", "Let me think..."
        # A "vision model" that gets images describes them.
        yield "content", "I see a red square" if messages[-1].get("images") else self.reply
        yield "stats", {"tokens": 5, "seconds": 0.5, "context": 50, "num_ctx": 8192, "cut_off": False}

    async def capabilities(self, model):
        if model.startswith("embed"):
            return ["embedding"]
        if model.startswith("thinker"):
            return ["completion", "thinking"]
        if model.startswith("eyes"):
            return ["completion", "vision"]
        if model.startswith("tooly"):
            return ["completion", "tools"]
        return ["completion"]

    async def list_models(self):
        return self.MODELS

    async def loaded_models(self):
        return self.loaded

    async def unload(self, model):
        self.unloaded.append(model)


@pytest.fixture
def fake(monkeypatch):
    fake = FakeOllama()
    # Patch a name where it is USED. stream_chat (in ollama.py) and the agent
    # loop (in tools.py) both look up ollama.stream_events, so replacing it
    # there reaches every answer: chat, Reverse, Guard, titles, summaries.
    monkeypatch.setattr(ollama, "stream_events", fake.stream_events)
    monkeypatch.setattr(ollama, "capabilities", fake.capabilities)
    monkeypatch.setattr(settings, "list_models", fake.list_models)
    monkeypatch.setattr(pages, "list_models", fake.list_models)

    monkeypatch.setattr(pages, "loaded_models", fake.loaded_models)
    monkeypatch.setattr(pages, "unload", fake.unload)

    # No embedding model: the Keeper falls back to searching by words.
    async def no_embeddings(texts):
        raise OllamaError("no embedding model in tests")

    monkeypatch.setattr(keeper, "embed", no_embeddings)
    return fake


@pytest.fixture
def client(db, fake):
    # A fixture can use other fixtures: every test with "client" also gets
    # a fresh database and the fake Ollama.
    import main  # imported here, so its init_db() already uses the test database

    return TestClient(main.app)
