# Tests for the research agent (cerberus/research.py). SearXNG, the web
# pages and the model are faked: the model's plan and report come from
# fake.script, one item per model call, in order.

import json

import pytest

from cerberus import database, research, webpage, websearch
from cerberus.websearch import WebError

PAGES = {
    "https://a.example/stripes": ("Why zebras have stripes", "Stripes keep biting flies away from zebras."),
    "https://b.example/flies": ("Fly study", "Flies land less often on striped surfaces, a 2019 study found."),
    "https://c.example/heat": ("Stripes and heat", "Stripes may also help zebras stay cool."),
}
# What each search finds. b.example is found by both: it must be read once.
RESULTS = {
    "zebra stripes purpose": ["https://a.example/stripes", "https://b.example/flies"],
    "zebra stripes flies study": ["https://b.example/flies", "https://c.example/heat"],
}


def fake_web(monkeypatch, down=False):
    searched, fetched = [], []

    async def search(base_url, query, limit=5):
        if down:
            raise WebError("SearXNG can't be reached.")
        searched.append(query)
        return [{"title": PAGES[url][0], "url": url, "snippet": ""} for url in RESULTS.get(query, [])]

    async def fetch_page(url):
        fetched.append(url)
        title, text = PAGES[url]
        return {"url": url, "title": title, "text": text}

    monkeypatch.setattr(websearch, "search", search)
    monkeypatch.setattr(webpage, "fetch_page", fetch_page)
    return searched, fetched


def ask(client, chat_id, text="Why do zebras have stripes?"):
    response = client.post("/research", json={"model": "small:3b", "chat_id": chat_id,
                                              "messages": [{"role": "user", "content": text}]})
    return [json.loads(line) for line in response.text.splitlines()]


PLAN = "1. zebra stripes purpose\n- zebra stripes flies study\n"
REPORT = "## Summary\nStripes keep flies away [1][2]."


# ---------- The plan ----------


def test_the_plan_is_cleaned_and_limited():
    answer = "Searches:\n1. Zebra stripes\n2) zebra stripes\n- \"zebra flies\"\n* zebra heat\n- zebra size\n- zebra age"
    assert research.parse_plan(answer, "q", "") == ["Zebra stripes", "zebra flies", "zebra heat", "zebra size"]


def test_a_search_with_guessed_numbers_is_dropped():
    # "1990" is in neither the question nor the chat: the model guessed it.
    assert research.parse_plan("zebra stripes 1990\nzebra stripes", "zebras?", "zebras?") == ["zebra stripes"]


def test_an_empty_plan_searches_the_question_itself():
    assert research.parse_plan("", "Why stripes?", "") == ["Why stripes?"]


def test_report_names_and_references():
    assert research.report_name("Compare local LLM runtimes?") == "research-compare-local-llm-runtimes.md"
    assert research.report_name("Τι είναι το Ollama;") == "research-τι-είναι-το-ollama.md"
    assert research.report_name("???") == "research-report.md"
    text = research.with_references("Report", [
        {"number": 1, "kind": "web", "name": "A [draft] page", "url": "https://a.example/"},
        {"number": 2, "kind": "attachment", "name": "notes.txt"},
    ])
    assert text == "Report\n\n## Sources\n\n1. [A (draft) page](https://a.example/)\n"


# ---------- The whole agent ----------


def test_research_plans_searches_reads_and_saves_a_report(client, fake, monkeypatch):
    searched, fetched = fake_web(monkeypatch)
    fake.script = [[("content", PLAN)], [("content", REPORT)]]
    project = database.create_project("Zoo")["id"]
    chat_id = database.create_chat("Zebras", project)["id"]

    events = ask(client, chat_id)

    # 1-2. The plan's searches, in order.
    assert searched == ["zebra stripes purpose", "zebra stripes flies study"]
    # 3. Each page read once, even though b.example was found twice.
    assert sorted(fetched) == sorted(PAGES)
    steps = [e["text"] for e in events if e["type"] == "progress"]
    assert steps[0] == "Planning the research…"
    assert any(step.startswith("Reading 3 pages") for step in steps)
    sources = [e for e in events if e["type"] == "sources"][-1]["sources"]
    assert {s["query"] for s in sources} == set(RESULTS)  # every search has evidence
    # 4. The report: streamed, saved with its sources, and as a document.
    assert "".join(e["text"] for e in events if e["type"] == "content") == REPORT
    assert events[-1]["saved"]
    chat = database.get_chat(chat_id)
    assert chat["messages"][-1]["content"] == REPORT
    assert chat["sources"]["1"][0]["kind"] == "web"
    saved = [e for e in events if e.get("document_id")]
    doc = database.get_document(saved[0]["document_id"])
    assert doc["name"] == "research-why-do-zebras-have-stripes.md"
    assert doc["project_id"] == project  # in the chat's own project
    assert "## Sources" in doc["content"] and "https://a.example/stripes" in doc["content"]


def test_the_writer_gets_the_sources_and_the_research_instructions(client, fake, monkeypatch):
    fake_web(monkeypatch)
    fake.script = [[("content", PLAN)], [("content", REPORT)]]
    ask(client, database.create_chat("Zebras")["id"])
    writer = fake.calls[-1]["messages"]
    assert "Research mode" in writer[0]["content"]
    assert "Stripes keep biting flies away" in writer[-1]["content"]


def test_without_searxng_nothing_is_saved(client, fake, monkeypatch):
    fake_web(monkeypatch, down=True)
    fake.script = [[("content", PLAN)]]
    chat_id = database.create_chat("Zebras")["id"]

    events = ask(client, chat_id)

    errors = [e["text"] for e in events if e["type"] == "error"]
    assert errors and "SearXNG can't be reached." in errors[0]
    assert not events[-1]["saved"]
    assert database.get_chat(chat_id)["messages"] == []
    assert database.list_documents() == []


def test_research_does_not_also_run_the_normal_web_search(client, fake, monkeypatch):
    searched, _ = fake_web(monkeypatch)
    fake.script = [[("content", PLAN)], [("content", REPORT)]]
    client.post("/research", json={"model": "small:3b", "chat_id": database.create_chat("Z")["id"], "web": True,
                                   "messages": [{"role": "user", "content": "Why do zebras have stripes?"}]})
    # Only the plan's searches: web=True must not add a search of the question.
    assert searched == list(RESULTS)
