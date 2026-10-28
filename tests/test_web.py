# Tests for web search inside the chat (Stage 3, step 3). SearXNG and the
# web pages are faked, so these run without internet: we only check what
# Cerberus does with the results.

import asyncio
import json

import pytest

from cerberus.storage import database
from cerberus.search import web, webpage, websearch
from cerberus.chat.prompts import WEB_NOTE
from cerberus.search.websearch import WebError

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
    assert sum(len(source["text"]) for source in sources) < 4 * 560


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
    from cerberus.storage import keeper
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


# ---------- Smart search: only when the message needs it ----------


@pytest.mark.parametrize("message", [
    "hello", "Hello there!", "thanks a lot", "ok", "how are you doing today?", "γεια σου",
    "thanks, that helped!", "Thank you so much for the explanation",
])
def test_small_talk_never_searches(message):
    assert asyncio.run(web.plan(message)) is None


def test_questions_about_you_never_search():
    # The Guard said "memory": the answer is in Cerberus, not on the internet.
    assert asyncio.run(web.plan("What is my favourite language?", memory=True)) is None


@pytest.mark.parametrize("message, searches", [
    ("What's the latest Python version?", True),  # "latest": it changes
    ("Write a poem about a dog", False),  # a task done from the message
    ("Translate this to Greek: good night", False),
    ("Explain how hash tables work", True),  # not sure: search
    ("What is 17 * 23?", False),  # plain arithmetic
    ("2^10 + 5", False),
])
def test_without_a_helper_the_rules_decide(message, searches):
    assert asyncio.run(web.plan(message)) == (message if searches else None)


def test_without_a_helper_a_follow_up_gets_the_earlier_question():
    recent = [{"role": "user", "content": "What's new in Python 3.15?"},
              {"role": "assistant", "content": "Lazy imports."}]
    query = asyncio.run(web.plan("and when was it released?", recent))
    assert query == "What's new in Python 3.15? and when was it released?"
    # A question that stands on its own is searched as it is.
    assert asyncio.run(web.plan("Who won the last Formula 1 race?", recent)) == "Who won the last Formula 1 race?"


def test_the_helper_turns_a_follow_up_into_a_real_query(fake):
    fake.script = [[("content", '"Python 3.15 release date"\n')]]
    recent = [{"role": "user", "content": "What's new in Python 3.15?"},
              {"role": "assistant", "content": "Lazy imports and faster startup."}]

    query = asyncio.run(web.plan("and when was it released?", recent, helper="small:3b"))

    assert query == "Python 3.15 release date"  # quotes and newline cleaned away
    sent = fake.calls[-1]["messages"][-1]["content"]
    assert "What's new in Python 3.15?" in sent and "and when was it released?" in sent


def test_the_helper_can_say_no(fake):
    fake.script = [[("content", "NONE")]]
    assert asyncio.run(web.plan("Tell me a joke about cats", helper="small:3b")) is None


def test_words_about_now_win_over_a_helper_that_says_no(fake):
    fake.script = [[("content", "NONE.")]]
    question = "What's the weather today in Athens?"
    assert asyncio.run(web.plan(question, helper="small:3b")) == question


def test_a_failing_helper_leaves_it_to_the_rules(fake, monkeypatch):
    from cerberus.engines import ollama

    async def broken(*args, **kwargs):
        raise ollama.OllamaError("helper crashed")
        yield

    monkeypatch.setattr(ollama, "stream_events", broken)
    question = "Who is the mayor of Athens?"
    assert asyncio.run(web.plan(question, helper="small:3b")) == question


def test_a_thinking_helper_is_not_asked(fake):
    # It would think for seconds just to say NONE, like in the Guard.
    question = "Tell me a joke about cats"
    assert asyncio.run(web.plan(question, helper="thinker:4b")) == question
    assert fake.calls == []


def test_hello_with_web_on_does_not_go_online(client, fake, monkeypatch):
    searched = fake_internet(monkeypatch, {"https://animals.example/zebra": ("Zebra facts", ZEBRA)})

    response = ask(client, text="hello")

    assert searched == []
    assert response.headers["X-Cerberus-Web"] == "skipped"
    assert all(event["type"] != "sources" for event in events(response))


def test_a_follow_up_is_searched_with_the_helpers_query(client, fake, monkeypatch):
    searched = fake_internet(monkeypatch, {"https://animals.example/zebra": ("Zebra facts", ZEBRA)})
    client.put("/settings", json={"helper_on": "yes", "helper_model": "small:3b"})
    # With the Helper on, the Guard asks it first ("chat"), then web.plan does.
    fake.script = [[("content", "chat")], [("content", "zebra stripes reason")]]

    response = client.post("/chat", json={"model": "small:3b", "web": True, "messages": [
        {"role": "user", "content": "Tell me about zebras"},
        {"role": "assistant", "content": "They are striped horses."},
        {"role": "user", "content": "why are they striped?"},
    ]})

    assert searched == ["zebra stripes reason"]
    sources = events(response)[0]["sources"]
    assert sources[0]["query"] == "zebra stripes reason"  # saved with the answer


def test_a_query_with_made_up_numbers_is_not_trusted(fake):
    # A real case: the Helper wrote its guess into the query, and the
    # search then found pages about the wrong date.
    fake.script = [[("content", "Python 3.15 was released on March 14, 2022")]]
    recent = [{"role": "user", "content": "What's new in Python 3.15?"},
              {"role": "assistant", "content": "Lazy imports."}]

    query = asyncio.run(web.plan("and when was it released?", recent, helper="small:3b"))

    # The rules' version instead: the earlier question in front.
    assert query == "What's new in Python 3.15? and when was it released?"


def test_numbers_from_the_conversation_are_fine(fake):
    fake.script = [[("content", "Python 3.15 release date")]]
    recent = [{"role": "user", "content": "What's new in Python 3.15?"}]
    assert asyncio.run(web.plan("and when was it released?", recent, helper="small:3b")) == "Python 3.15 release date"
