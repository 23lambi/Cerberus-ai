# Tests for web search, without the internet or a real SearXNG.
# httpx.MockTransport is a fake network: every request goes to our own
# function, which decides the answer. The rest of httpx works as usual.

import asyncio

import httpx
import pytest

from cerberus import websearch

URL = "http://127.0.0.1:8888"


def fake_searxng(monkeypatch, handler):
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


def test_search_asks_for_json_and_cleans_the_results(monkeypatch):
    requests = fake_searxng(monkeypatch, results(
        {"title": " Python docs ", "url": "https://docs.python.org/3/", "content": "The docs."},
        {"title": "Same page again", "url": "https://docs.python.org/3/", "content": ""},
        {"title": "A torrent", "url": "magnet:?xt=urn:btih:abc", "content": ""},
        {"url": "http://example.com/"},  # no title, no snippet
    ))

    found = asyncio.run(websearch.search(URL + "/", "python & asyncio"))

    assert found == [
        {"title": "Python docs", "url": "https://docs.python.org/3/", "snippet": "The docs."},
        {"title": "http://example.com/", "url": "http://example.com/", "snippet": ""},
    ]
    sent = requests[0].url
    assert sent.path == "/search"
    assert sent.params["q"] == "python & asyncio" and sent.params["format"] == "json"


def test_search_keeps_only_the_first_few(monkeypatch):
    many = [{"title": str(i), "url": f"https://example.com/{i}"} for i in range(20)]
    fake_searxng(monkeypatch, results(*many))
    assert len(asyncio.run(websearch.search(URL, "x", limit=3))) == 3


def test_json_switched_off_is_explained(monkeypatch):
    fake_searxng(monkeypatch, lambda request: httpx.Response(403))
    with pytest.raises(websearch.WebError, match="settings.yml"):
        asyncio.run(websearch.search(URL, "x"))


def test_searxng_not_running_is_explained(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    fake_searxng(monkeypatch, refuse)
    with pytest.raises(websearch.WebError, match="sudo docker start searxng"):
        asyncio.run(websearch.search(URL, "x"))


def test_an_answer_that_is_not_json_is_an_error(monkeypatch):
    fake_searxng(monkeypatch, lambda request: httpx.Response(200, text="<html>oops</html>"))
    with pytest.raises(websearch.WebError, match="could not be read"):
        asyncio.run(websearch.search(URL, "x"))
