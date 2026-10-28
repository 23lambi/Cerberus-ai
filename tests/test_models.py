# Tests for the Models panel: reading ollama.com's search page, and the
# routes to list, download and delete models. Ollama and ollama.com are
# faked, so nothing is downloaded or deleted for real.

import json

import pytest

from cerberus import library, ollama

# A small hand-written page shaped like ollama.com/search: a link per
# model, a description, tags, sizes, and a download count.
SEARCH_PAGE = """
<ul>
  <li><a href="/library/qwen3">
    <h2><span>qwen3</span></h2>
    <div><span>tools</span><span>thinking</span></div>
    <p>Qwen3 is the latest   generation of models.</p>
    <div><span title="12,345,678 downloads"><svg></svg><span>12.3M</span></span>
      <span>0.6b</span><span>4b</span><span>30b</span></div>
  </a></li>
  <li><a href="/library/nomic-embed-text">
    <h2><span>nomic-embed-text</span></h2>
    <div><span>embedding</span></div>
    <p>A text embedding model.</p>
    <div><span title="9,000 downloads"><span>9K</span></span></div>
  </a></li>
  <li><a href="/library/qwen3">duplicate link</a></li>
  <li><a href="/blog/not-a-model">Blog</a></li>
</ul>
"""


def test_the_search_page_becomes_models():
    assert library.parse(SEARCH_PAGE) == [
        {"name": "qwen3", "description": "Qwen3 is the latest generation of models.",
         "capabilities": ["tools", "thinking"], "sizes": ["0.6b", "4b", "30b"], "downloads": "12,345,678"},
        {"name": "nomic-embed-text", "description": "A text embedding model.",
         "capabilities": ["embedding"], "sizes": [], "downloads": "9,000"},
    ]


# Shaped like ollama.com/library: the statistics are in a second <p>.
LIBRARY_PAGE = """
<li><a href="/library/gemma3">
  <div><h2><span>gemma3</span></h2><p>Runs on a single GPU.</p></div>
  <div><div><span>vision</span><span>1b</span><span>4b</span></div>
    <p><span><svg></svg><span>41.5M</span><span>&nbsp;Pulls</span></span>
       <span><span>29</span><span>&nbsp;Tags</span></span>
       <span><span>Updated&nbsp;</span><span>2 weeks ago</span></span></p></div>
</a></li>
"""


def test_the_library_page_becomes_models():
    assert library.parse(LIBRARY_PAGE) == [
        {"name": "gemma3", "description": "Runs on a single GPU.",
         "capabilities": ["vision"], "sizes": ["1b", "4b"], "downloads": "41.5M"},
    ]


def test_a_redesigned_page_finds_nothing_instead_of_crashing():
    assert library.parse("<html><body><h1>New design</h1></body></html>") == []


def test_installed_models_with_details(client, monkeypatch):
    async def installed():
        return [{"name": "eyes:4b", "size": 3_000_000_000, "parameters": "3.9B",
                 "quantization": "Q4_K_M", "family": "gemma3"}]

    async def running():
        return {"eyes:4b": 2_500_000_000}

    monkeypatch.setattr(ollama, "installed", installed)
    monkeypatch.setattr(ollama, "running", running)
    model = client.get("/models/installed").json()["models"][0]
    assert model["in_memory"] == 2_500_000_000
    assert "vision" in model["capabilities"]  # from the fake Ollama in conftest


def test_ollama_not_running_is_explained(client, monkeypatch):
    async def down():
        raise ollama.OllamaError(ollama.NOT_RUNNING)

    monkeypatch.setattr(ollama, "installed", down)
    response = client.get("/models/installed")
    assert response.status_code == 503 and "ollama serve" in response.json()["detail"]


def test_a_download_streams_its_progress(client, monkeypatch):
    pulled = []

    async def pull(model):
        pulled.append(model)
        yield {"status": "pulling manifest"}
        yield {"status": "pulling 6a0746a1ec1a", "completed": 50, "total": 100}
        yield {"status": "success"}

    monkeypatch.setattr(ollama, "pull", pull)
    events = [json.loads(line) for line in client.post("/models/pull", json={"model": " qwen3:4b "}).text.splitlines()]
    assert pulled == ["qwen3:4b"]
    assert events[1] == {"type": "progress", "status": "pulling 6a0746a1ec1a", "completed": 50, "total": 100}
    assert events[-1] == {"type": "done", "model": "qwen3:4b"}


def test_a_failed_download_says_why(client, monkeypatch):
    async def pull(model):
        raise ollama.OllamaError("pull model manifest: file does not exist")
        yield

    monkeypatch.setattr(ollama, "pull", pull)
    events = [json.loads(line) for line in client.post("/models/pull", json={"model": "nope:1b"}).text.splitlines()]
    assert events == [{"type": "error", "text": "pull model manifest: file does not exist"}]


@pytest.mark.parametrize("name", ["", "  ", "-rf", "qwen3; rm -rf ~", "../../etc", "a b"])
def test_strange_names_are_refused(client, monkeypatch, name):
    async def must_not_run(model):
        raise AssertionError("Ollama must not be asked")
        yield

    monkeypatch.setattr(ollama, "pull", must_not_run)
    assert client.post("/models/pull", json={"model": name}).status_code == 422
    assert client.delete("/models/installed", params={"name": name}).status_code == 422


def test_delete_a_model(client, monkeypatch):
    deleted = []

    async def delete(model):
        if model == "missing:1b":
            raise ollama.OllamaError("model 'missing:1b' not found")
        deleted.append(model)

    monkeypatch.setattr(ollama, "delete", delete)
    assert client.delete("/models/installed", params={"name": "hf.co/user/model:Q4_K_M"}).json() == {
        "deleted": "hf.co/user/model:Q4_K_M"}
    assert deleted == ["hf.co/user/model:Q4_K_M"]
    assert client.delete("/models/installed", params={"name": "missing:1b"}).status_code == 404


def test_library_search_offline(client, monkeypatch):
    async def offline(query):
        raise library.LibraryError("ollama.com could not be reached. Are you online?")

    monkeypatch.setattr(library, "search", offline)
    response = client.get("/models/library", params={"q": "qwen"})
    assert response.status_code == 502 and "online" in response.json()["detail"]


# ---------- Browsing the library without searching ----------


def test_browsing_without_words_lists_popular_or_newest(client, monkeypatch):
    asked = []

    async def fetch(url, params=None):
        asked.append(url)
        return SEARCH_PAGE

    monkeypatch.setattr(library, "fetch", fetch)
    monkeypatch.setattr(library, "browse_cache", {})
    assert [m["name"] for m in client.get("/models/library").json()["models"]] == ["qwen3", "nomic-embed-text"]
    client.get("/models/library", params={"order": "newest"})
    assert asked == [library.LIBRARY_URL, library.SEARCH_URL]


def test_the_browse_list_is_kept_for_an_hour(monkeypatch):
    import asyncio
    calls = []

    async def fetch(url, params=None):
        calls.append(url)
        return SEARCH_PAGE

    clock = [1000.0]
    monkeypatch.setattr(library, "fetch", fetch)
    monkeypatch.setattr(library, "browse_cache", {})
    monkeypatch.setattr(library.time, "monotonic", lambda: clock[0])
    asyncio.run(library.browse())
    clock[0] += 3599  # just under an hour: from the cache
    asyncio.run(library.browse())
    assert len(calls) == 1
    clock[0] += 2  # older than an hour: asked again
    asyncio.run(library.browse())
    assert len(calls) == 2


def test_a_failed_browse_is_not_kept(monkeypatch):
    import asyncio

    async def offline(url, params=None):
        raise library.LibraryError("ollama.com could not be reached. Are you online?")

    monkeypatch.setattr(library, "fetch", offline)
    monkeypatch.setattr(library, "browse_cache", {})
    with pytest.raises(library.LibraryError):
        asyncio.run(library.browse())
    assert library.browse_cache == {}  # the next try asks again


def test_local_apps_discovery_lists_running_servers_without_keys(client, monkeypatch):
    from cerberus import openai_api
    calls = []

    async def list_models(engine, timeout):
        calls.append((engine["url"], timeout))
        if engine["preset"] == "jan":
            raise openai_api.EngineError("offline")
        return ["my-local-model"]

    monkeypatch.setattr(openai_api, "list_models", list_models)
    response = client.get("/models/local")
    assert response.status_code == 200
    found = response.json()["engines"]
    assert [engine["preset"] for engine in found] == ["lmstudio", "llamacpp"]
    assert all(engine["models"] == ["my-local-model"] for engine in found)
    assert all("key" not in engine for engine in found)
    assert len(calls) == 3 and all(timeout == 2 for _, timeout in calls)
    assert all(url.startswith("http://127.0.0.1:") for url, _ in calls)


def test_local_apps_include_configured_local_address_and_keep_its_key_private(client, monkeypatch):
    from cerberus import keys, openai_api, settings
    settings.update({"engine": "openai", "openai_preset": "custom", "openai_url": "http://127.0.0.1:9123/v1"})
    keys.set("openai_key", "private-local-key")
    seen = []

    async def list_models(engine, timeout):
        seen.append(engine)
        return []

    monkeypatch.setattr(openai_api, "list_models", list_models)
    response = client.get("/models/local")
    assert response.json()["engines"][0]["url"] == "http://127.0.0.1:9123/v1"
    assert seen[0]["key"] == "private-local-key"
    assert "private-local-key" not in response.text
    assert len(seen) == 4


def test_local_discovery_never_probes_cloud_provider(client, monkeypatch):
    from cerberus import openai_api, settings
    settings.update({"engine": "openai", "openai_preset": "openai", "openai_url": ""})
    calls = []

    async def list_models(engine, timeout):
        calls.append(engine["url"])
        raise openai_api.EngineError("offline")

    monkeypatch.setattr(openai_api, "list_models", list_models)
    assert client.get("/models/local").json() == {"engines": []}
    assert len(calls) == 3
    assert all("127.0.0.1" in url for url in calls)


def test_configured_default_local_endpoint_is_probed_once(client, monkeypatch):
    from cerberus import openai_api, settings
    settings.update({"engine": "openai", "openai_preset": "lmstudio", "openai_url": ""})
    calls = []

    async def list_models(engine, timeout):
        calls.append(engine["url"])
        return []

    monkeypatch.setattr(openai_api, "list_models", list_models)
    found = client.get("/models/local").json()["engines"]
    assert len(found) == len(set(calls)) == 3


def test_local_discovery_reads_openai_model_lists(client, monkeypatch):
    import httpx
    from cerberus import openai_api

    def handler(request):
        if request.url.port != 1234:
            raise httpx.ConnectError("not running")
        assert request.url.path == "/v1/models"
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"data": [{"id": "local-chat-model"}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(openai_api.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    found = client.get("/models/local").json()["engines"]
    assert len(found) == 1
    assert found[0]["name"] == "LM Studio"
    assert found[0]["models"] == ["local-chat-model"]
