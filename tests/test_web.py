# Tests for web search inside the chat (Stage 3, step 3). SearXNG and the
# web pages are faked, so these run without internet: we only check what
# Cerberus does with the results.

import asyncio
import json

import pytest

from cerberus import database, web, webpage, websearch
from cerberus.prompts import WEB_NOTE
from cerberus.websearch import WebError

ZEBRA = "Zebras have black and white stripes. Every zebra's stripes are unique."
FILLER = "This paragraph is about something else entirely, like cooking pasta. " * 30


def fake_internet(monkeypatch, pages, broken=()):
    """pages: {url: (title, text)}. URLs in broken can't be downloaded."""
    searched = []

    async def search(base_url, query, limit=5):
        searched.append(query)
        return [{"title": title, "url": url, "snippet": f"snippet of {title}"}
                for url, (title, _) in pages.items()]

    async def fetch_page(url):
        if url in broken:
            raise WebError("blocked")
        title, text = pages[url]
        return {"url": url, "title": title, "text": text}

    monkeypatch.setattr(websearch, "search", search)
    monkeypatch.setattr(webpage, "fetch_page", fetch_page)
    return searched


def ask(client, text="Why do zebras have stripes?", web_on=True, chat_id=None):
    return client.post("/chat", json={"model": "small:3b", "chat_id": chat_id, "web": web_on,
                                      "messages": [{"role": "user", "content": text}]})


def events(response):
    return [json.loads(line) for line in response.text.splitlines()]


# ---------- research(): from search results to sources ----------


def test_research_keeps_the_pieces_about_the_question(db, fake, monkeypatch):
    fake_internet(monkeypatch, {
        "https://animals.example/zebra": ("Zebra facts", FILLER + "\n\n" + ZEBRA + "\n\n" + FILLER),
        "https://other.example/": ("Other", FILLER),
    })
    sources = asyncio.run(web.research("http://searx", "Why do zebras have stripes?"))

    first = sources[0]
    assert first["name"] == "Zebra facts (animals.example)"
    assert first["url"] == "https://animals.example/zebra"
    assert first["kind"] == "web"
    assert "unique" in first["text"]
    # Never whole pages: only a few pieces of about 800 characters reach the model.
    assert sum(len(source["text"]) for source in sources) < 4 * 900


def test_a_page_that_cannot_be_read_falls_back_to_its_snippet(db, fake, monkeypatch):
    fake_internet(monkeypatch, {"https://blocked.example/": ("Blocked page", "never read")},
                  broken={"https://blocked.example/"})
    sources = asyncio.run(web.research("http://searx", "anything"))
    assert sources[0]["text"] == "snippet of Blocked page"


# ---------- In the chat ----------


def test_web_sources_reach_the_model_and_are_saved(client, fake, monkeypatch):
    searched = fake_internet(monkeypatch, {"https://animals.example/zebra": ("Zebra facts", ZEBRA)})
    chat_id = client.post("/chats", json={}).json()["id"]

    response = ask(client, chat_id=chat_id)

    assert searched == ["Why do zebras have stripes?"]
    assert response.headers["X-Cerberus-Web"] == "1"
    assert response.headers["X-Cerberus-Documents"] == "0"  # web pages aren't documents
    first = events(response)[0]
    assert first["type"] == "sources" and first["sources"][0]["kind"] == "web"
    sent = fake.calls[-1]["messages"][-1]["content"]
    assert ZEBRA in sent and WEB_NOTE.strip() in sent
    # Saved like document sources: still there when the chat is reopened.
    assert database.get_chat(chat_id)["sources"]["1"][0]["url"] == "https://animals.example/zebra"


def test_without_the_web_box_nothing_goes_online(client, fake, monkeypatch):
    searched = fake_internet(monkeypatch, {"https://animals.example/zebra": ("Zebra facts", ZEBRA)})
    response = ask(client, web_on=False)
    assert searched == []
    assert "X-Cerberus-Web" not in response.headers
    assert ZEBRA not in fake.calls[-1]["messages"][-1]["content"]


def test_searxng_down_still_gives_an_answer_and_says_why(client, fake, monkeypatch):
    async def down(base_url, query, limit=5):
        raise WebError("SearXNG can't be reached.")

    monkeypatch.setattr(websearch, "search", down)
    response = ask(client)

    assert response.status_code == 200
    assert response.headers["X-Cerberus-Web"] == "0"
    assert response.headers["X-Cerberus-Web-Error"] == "SearXNG can't be reached."
    assert [e["type"] for e in events(response)] == ["content", "stats", "done"]
    sent = fake.calls[-1]["messages"][-1]["content"]
    assert "web search, but it failed: SearXNG can't be reached." in sent


def test_web_pages_are_dropped_before_your_message_is_refused(client, fake, monkeypatch, tmp_path):
    # A big attached file that only fits WITHOUT the web pieces.
    from cerberus import keeper
    monkeypatch.setattr(keeper, "DOCUMENTS_DIR", str(tmp_path))
    fake_internet(monkeypatch, {"https://animals.example/zebra": ("Zebra facts", (ZEBRA + " ") * 40)})
    chat_id = client.post("/chats", json={}).json()["id"]
    client.post(f"/documents?name=big.txt&chat_id={chat_id}", content=b"y " * 9750)

    response = ask(client, chat_id=chat_id)

    assert response.status_code == 200
    assert response.headers["X-Cerberus-Web"] == "0"
    sent = fake.calls[-1]["messages"][-1]["content"]
    assert "Zebra facts" not in sent
    assert WEB_NOTE.strip() not in sent  # the warning left together with the pages


@pytest.mark.parametrize("route", ["/chat", "/council"])
def test_deep_think_gets_the_web_too(client, fake, monkeypatch, route):
    fake_internet(monkeypatch, {"https://animals.example/zebra": ("Zebra facts", ZEBRA)})
    response = client.post(route, json={"model": "small:3b", "web": True,
                                        "messages": [{"role": "user", "content": "Why do zebras have stripes?"}]})
    assert response.headers["X-Cerberus-Web"] == "1"
    assert all(ZEBRA in str(call["messages"]) for call in fake.calls[-3:] if route == "/council")
