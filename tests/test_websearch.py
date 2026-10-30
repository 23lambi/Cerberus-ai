# Tests for web search, without the internet or a real search engine.
# httpx.MockTransport is a fake network: every request goes to our own
# function, which decides the answer. The rest of httpx works as usual.

import asyncio
import json

import httpx
import pytest

from cerberus.core import settings
from cerberus.search import websearch
from cerberus.storage import keys

URL = "http://127.0.0.1:8888"


@pytest.fixture(autouse=True)
def fresh_settings(db):
    # Every test gets its own empty database, so the engine is the default
    # (SearXNG) unless a test chooses another one.
    pass


def fake_engine(monkeypatch, handler):
    requests = []

    def record(request):
        requests.append(request)
        return handler(request)

    monkeypatch.setattr(
        websearch, "new_client",
        lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(record)),
    )
    return requests


def results(*items):
    return lambda request: httpx.Response(200, json={"results": list(items)})


def search(query="x", **options):
    return asyncio.run(websearch.search(query, **options))


# ---------- SearXNG (the default) ----------


def test_search_asks_for_json_and_cleans_the_results(monkeypatch):
    settings.update({"web_url": URL + "/"})
    requests = fake_engine(monkeypatch, results(
        {"title": " Python docs ", "url": "https://docs.python.org/3/", "content": "The docs."},
        {"title": "Same page again", "url": "https://docs.python.org/3/", "content": ""},
        {"title": "A torrent", "url": "magnet:?xt=urn:btih:abc", "content": ""},
        {"url": "http://example.com/"},  # no title, no snippet
    ))

    found = search("python & asyncio")

    assert found == [
        {"title": "Python docs", "url": "https://docs.python.org/3/", "snippet": "The docs."},
        {"title": "http://example.com/", "url": "http://example.com/", "snippet": ""},
    ]
    sent = requests[0].url
    assert sent.host == "127.0.0.1" and sent.path == "/search"
    assert sent.params["q"] == "python & asyncio" and sent.params["format"] == "json"


def test_search_keeps_only_the_first_few(monkeypatch):
    many = [{"title": str(i), "url": f"https://example.com/{i}"} for i in range(20)]
    fake_engine(monkeypatch, results(*many))
    assert len(search(limit=3)) == 3


def test_json_switched_off_is_explained(monkeypatch):
    fake_engine(monkeypatch, lambda request: httpx.Response(403))
    with pytest.raises(websearch.WebError, match="settings.yml"):
        search()


def test_searxng_not_running_is_explained(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    fake_engine(monkeypatch, refuse)
    with pytest.raises(websearch.WebError, match="docker start searxng"):
        search()


def test_an_answer_that_is_not_json_is_an_error(monkeypatch):
    fake_engine(monkeypatch, lambda request: httpx.Response(200, text="<html>oops</html>"))
    with pytest.raises(websearch.WebError, match="could not be read"):
        search()


# ---------- DuckDuckGo ----------

DUCKDUCKGO_PAGE = """
<div class="result results_links result--ad">
  <a class="result__a" href="https://ads.example/">Buy now</a>
  <a class="result__snippet" href="https://ads.example/">An ad</a>
</div>
<div class="result results_links web-result">
  <a class="result__a" href="https://docs.python.org/3/library/asyncio.html">asyncio &mdash; docs</a>
  <a class="result__snippet" href="#"><b>asyncio</b> is a library</a>
</div>
<div class="result results_links web-result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Frealpython.com%2Fasync%2F&rut=1">Real Python</a>
</div>
"""


def test_duckduckgo_reads_the_results_page_without_ads(monkeypatch):
    settings.update({"web_engine": "duckduckgo"})
    requests = fake_engine(monkeypatch, lambda request: httpx.Response(200, text=DUCKDUCKGO_PAGE))

    found = search("python asyncio")

    assert found == [
        {"title": "asyncio — docs", "url": "https://docs.python.org/3/library/asyncio.html",
         "snippet": "asyncio is a library"},
        # The redirect around the address is taken off.
        {"title": "Real Python", "url": "https://realpython.com/async/", "snippet": ""},
    ]
    assert requests[0].method == "POST" and requests[0].url.host == "html.duckduckgo.com"
    assert b"q=python+asyncio" in requests[0].content


def test_a_duckduckgo_captcha_is_explained(monkeypatch):
    settings.update({"web_engine": "duckduckgo"})
    fake_engine(monkeypatch, lambda request: httpx.Response(200, text='<form id="challenge-form"></form>'))
    with pytest.raises(websearch.WebError, match="CAPTCHA"):
        search()


# ---------- Brave Search and Tavily ----------


def test_brave_sends_the_key_and_strips_the_bold_marks(monkeypatch):
    settings.update({"web_engine": "brave", "brave_key": "brave-secret"})
    requests = fake_engine(monkeypatch, lambda request: httpx.Response(200, json={"web": {"results": [
        {"title": "<strong>Python</strong> &amp; you", "url": "https://python.org/",
         "description": "Learn <strong>Python</strong>."},
    ]}}))

    assert search("python", limit=3) == [
        {"title": "Python & you", "url": "https://python.org/", "snippet": "Learn Python."},
    ]
    sent = requests[0]
    assert sent.url.host == "api.search.brave.com"
    assert sent.headers["X-Subscription-Token"] == "brave-secret"
    assert sent.url.params["count"] == "3"


def test_tavily_sends_the_key_and_reads_the_results(monkeypatch):
    settings.update({"web_engine": "tavily", "tavily_key": "tvly-secret"})
    requests = fake_engine(monkeypatch, results(
        {"title": "Zebras", "url": "https://zebra.example/", "content": "Stripes.", "score": 0.9},
    ))

    assert search("zebras") == [{"title": "Zebras", "url": "https://zebra.example/", "snippet": "Stripes."}]
    sent = requests[0]
    assert sent.headers["Authorization"] == "Bearer tvly-secret"
    assert json.loads(sent.content) == {"query": "zebras", "max_results": 5}


@pytest.mark.parametrize("engine", ["brave", "tavily"])
def test_an_engine_without_its_key_says_so_and_sends_nothing(monkeypatch, engine):
    settings.update({"web_engine": engine})
    requests = fake_engine(monkeypatch, results())
    with pytest.raises(websearch.WebError, match="needs an API key"):
        search()
    assert requests == []


def test_a_refused_key_is_explained(monkeypatch):
    settings.update({"web_engine": "tavily", "tavily_key": "wrong"})
    fake_engine(monkeypatch, lambda request: httpx.Response(401))
    with pytest.raises(websearch.WebError, match="refused the API key"):
        search()


# ---------- Settings ----------


def test_search_keys_stay_private_and_reset_removes_them():
    settings.update({"brave_key": "b", "tavily_key": "t"})
    values = settings.get_all()
    assert values["brave_key_set"] == "yes" and values["tavily_key_set"] == "yes"
    assert "b" not in values.values() and "t" not in values.values()
    assert keys.get("brave_key") == "b"

    settings.reset()
    assert keys.get("brave_key") == "" and keys.get("tavily_key") == ""


def test_an_unknown_engine_is_not_saved():
    settings.update({"web_engine": "altavista"})
    assert settings.get("web_engine") == "searxng"


# ---------- On every system ----------


@pytest.mark.parametrize("platform_name, command", [
    ("linux", "sudo docker start searxng"),
    ("darwin", "docker start searxng"),  # Docker Desktop: no sudo
    ("win32", "docker start searxng"),
])
def test_docker_commands_fit_the_system(platform_name, command):
    assert websearch.docker("start searxng", platform_name) == command


# ---------- The Setup window ----------


def test_setup_shows_the_chosen_engine_without_keys(monkeypatch):
    from cerberus.core import setup

    settings.update({"web_engine": "brave"})
    state = asyncio.run(setup.web_status())
    assert state["name"] == "Brave Search" and state["status"] == "no_key"

    settings.update({"brave_key": "brave-secret"})
    state = asyncio.run(setup.web_status())
    assert state["status"] == "ready" and state["brave_key_set"] == "yes"
    assert "brave-secret" not in str(state)

    settings.update({"web_engine": "duckduckgo"})
    assert asyncio.run(setup.web_status())["status"] == "ready"


def test_save_and_test_searches_once_with_the_saved_engine(client, monkeypatch):
    settings.update({"web_engine": "tavily", "tavily_key": "tvly-secret"})
    requests = fake_engine(monkeypatch, results({"title": "Cerberus", "url": "https://dog.example/"}))

    assert client.post("/setup/web/test").json() == {"ok": True, "count": 1, "first": "Cerberus"}
    assert len(requests) == 1

    fake_engine(monkeypatch, results())
    answer = client.post("/setup/web/test").json()
    assert answer == {"ok": False, "error": "Tavily answered, but found nothing."}

    fake_engine(monkeypatch, lambda request: httpx.Response(401))
    assert "refused the API key" in client.post("/setup/web/test").json()["error"]
