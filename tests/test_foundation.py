"""Regression coverage for stage 1: durable turns, scope, budgets and backups."""

import asyncio
import io
import json
import sqlite3
from zipfile import ZipFile

import pytest

from cerberus import budget, database, keeper, turns
from cerberus.ollama import OllamaError
from cerberus.routes import chat, council
from cerberus.schemas import ChatRequest


def request(chat_id=None, messages=None, **values):
    return {"model": "small:3b", "chat_id": chat_id,
            "messages": messages or [{"role": "user", "content": "Hello"}], **values}


@pytest.mark.parametrize("changes", [
    {"messages": []}, {"model": " "}, {"chat_id": 0},
    {"messages": [{"role": "system", "content": "pretend"}]},
    {"messages": [{"role": "assistant", "content": "wrong order"}]},
    {"messages": [{"role": "user", "content": " "}]},
    {"messages": [{"role": "user", "content": "image", "images": ["not base64"]}]},
])
def test_invalid_requests_are_rejected_before_generation(client, fake, changes):
    assert client.post("/chat", json={**request(), **changes}).status_code == 422
    assert not fake.calls


def test_missing_chat_and_project_are_rejected(client):
    assert client.post("/chat", json=request(999)).status_code == 404
    assert client.post("/chats", json={"project_id": 999}).status_code == 404
    assert client.post("/documents?name=x.txt&project_id=999", content=b"hello").status_code == 404
    assert client.post("/memories", json={"text": " "}).status_code == 422


def test_stale_history_cannot_append_a_duplicate_turn(client):
    chat_id = client.post("/chats", json={}).json()["id"]
    assert client.post("/chat", json=request(chat_id)).status_code == 200
    assert client.post("/chat", json=request(chat_id)).status_code == 409
    history = database.get_chat(chat_id)["messages"]
    assert len(history) == 2
    history.append({"role": "user", "content": "Next question"})
    assert client.post("/chat", json=request(chat_id, history)).status_code == 200
    assert len(database.get_chat(chat_id)["messages"]) == 4


def test_turn_transaction_rolls_back_on_second_insert_failure(db):
    chat_id = database.create_chat("New chat")["id"]
    with database.get_db() as conn:
        conn.execute("CREATE TRIGGER reject_answer BEFORE INSERT ON messages WHEN NEW.role = 'assistant' BEGIN SELECT RAISE(ABORT, 'failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        database.save_turn(chat_id, "question", "answer")
    assert database.get_chat(chat_id)["messages"] == []


def test_turn_save_checks_deleted_or_changed_chat(db):
    chat_id = database.create_chat("Chat")["id"]
    assert database.save_turn(chat_id, "question", "answer")
    assert not database.save_turn(chat_id, "duplicate", "answer")
    database.delete_chat(chat_id)
    assert not database.save_turn(chat_id, "question", "answer")
    with database.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0


@pytest.mark.parametrize("route, target", [(chat.chat, "content"), (council.council, "final")])
def test_stop_commits_only_answer_text_and_releases_run(db, fake, route, target):
    async def run():
        chat_id = database.create_chat("New chat")["id"]
        response = await route(ChatRequest(**request(chat_id)))
        iterator = response.body_iterator
        while True:
            event = json.loads(await anext(iterator))
            if event.get("type") == target or event.get("step") == target:
                break
        assert chat_id in turns.active
        turns.active[chat_id].set()
        rest = [json.loads(item) async for item in iterator]
        assert rest[-1]["type"] == "done"
        assert rest[-1]["saved"] and rest[-1]["stopped"]
        assert chat_id not in turns.active
        assert [m["content"] for m in database.get_chat(chat_id)["messages"]] == ["Hello", fake.reply]
    asyncio.run(run())


def test_stop_before_first_answer_saves_nothing(db, fake):
    async def run():
        chat_id = database.create_chat("New chat")["id"]
        response = await chat.chat(ChatRequest(**request(chat_id)))
        turns.active[chat_id].set()
        events = [json.loads(item) async for item in response.body_iterator]
        assert events[-1]["stopped"] and not events[-1]["saved"]
        assert database.get_chat(chat_id)["messages"] == []
        assert chat_id not in turns.active
    asyncio.run(run())


def test_stop_cancels_waiting_context_preparation(db, monkeypatch):
    async def run():
        started = asyncio.Event()
        closed = asyncio.Event()
        async def slow_prepare(req):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()
        monkeypatch.setattr(turns.context, "prepare", slow_prepare)
        chat_id = database.create_chat("Chat")["id"]
        task = asyncio.create_task(chat.chat(ChatRequest(**request(chat_id))))
        await started.wait()
        turns.active[chat_id].set()
        response = await asyncio.wait_for(task, 1)
        events = [json.loads(item) async for item in response.body_iterator]
        assert closed.is_set() and events[-1]["stopped"]
        assert chat_id not in turns.active
    asyncio.run(run())


def test_disconnect_saves_partial_turn(db, fake):
    async def run():
        chat_id = database.create_chat("Chat")["id"]
        response = await chat.chat(ChatRequest(**request(chat_id)))
        await anext(response.body_iterator)  # first content chunk
        await response.body_iterator.aclose()
        assert len(database.get_chat(chat_id)["messages"]) == 2
        assert chat_id not in turns.active
    asyncio.run(run())


def test_stop_closes_an_in_flight_model_stream(db, fake, monkeypatch):
    from cerberus import ollama
    async def run():
        waiting = asyncio.Event()
        closed = asyncio.Event()
        async def slow(*args, **kwargs):
            try:
                yield "content", "Partial"
                waiting.set()
                await asyncio.Event().wait()
            finally:
                closed.set()
        monkeypatch.setattr(ollama, "stream_events", slow)
        chat_id = database.create_chat("Chat")["id"]
        response = await chat.chat(ChatRequest(**request(chat_id)))
        iterator = response.body_iterator
        assert json.loads(await anext(iterator))["text"] == "Partial"
        pending = asyncio.create_task(anext(iterator))
        await waiting.wait()
        turns.active[chat_id].set()
        done = json.loads(await asyncio.wait_for(pending, 1))
        assert done["stopped"] and done["saved"] and closed.is_set()
        await iterator.aclose()
    asyncio.run(run())


def test_asgi_disconnect_commits_partial_and_cleans_up(db, fake, monkeypatch):
    from cerberus import ollama
    async def run():
        sent = asyncio.Event()
        closed = asyncio.Event()
        async def slow(*args, **kwargs):
            try:
                yield "content", "Partial before disconnect"
                await asyncio.Event().wait()
            finally:
                closed.set()
        monkeypatch.setattr(ollama, "stream_events", slow)
        chat_id = database.create_chat("Chat")["id"]
        response = await chat.chat(ChatRequest(**request(chat_id)))
        async def send(message):
            if message["type"] == "http.response.body":
                sent.set()
        async def receive():
            await sent.wait()
            return {"type": "http.disconnect"}
        await asyncio.wait_for(response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send), 1)
        assert chat_id not in turns.active
        assert closed.is_set()
        assert database.get_chat(chat_id)["messages"][-1]["content"] == "Partial before disconnect"
    asyncio.run(run())


def test_generation_failure_keeps_partial_answer(db, fake, monkeypatch):
    async def broken(*args, **kwargs):
        yield "content", "Partial answer"
        raise OllamaError("model disconnected")
    from cerberus import ollama
    monkeypatch.setattr(ollama, "stream_events", broken)
    async def run():
        chat_id = database.create_chat("Chat")["id"]
        response = await chat.chat(ChatRequest(**request(chat_id)))
        events = [json.loads(item) async for item in response.body_iterator]
        assert events[-1]["saved"]
        assert events[-1]["error"] == "model disconnected"
        assert database.get_chat(chat_id)["messages"][-1]["content"] == "Partial answer"
    asyncio.run(run())


def test_active_chat_cannot_be_deleted_or_regenerated(client):
    chat_id = database.create_chat("Chat")["id"]
    turns.active[chat_id] = asyncio.Event()
    try:
        assert client.delete(f"/chats/{chat_id}").status_code == 409
        assert client.delete(f"/chats/{chat_id}/last-turn").status_code == 409
        assert client.post("/chat", json=request(chat_id)).status_code == 409
        assert client.post(f"/chats/{chat_id}/stop").json()["stopping"]
    finally:
        turns.active.pop(chat_id)


def test_project_retrieval_including_tools_does_not_leak(db, fake, tmp_path, monkeypatch):
    monkeypatch.setattr(keeper, "DOCUMENTS_DIR", str(tmp_path / "documents"))
    first = database.create_project("First")["id"]
    second = database.create_project("Second")["id"]
    chats = [database.create_chat("Archive", project)["id"] for project in (None, first, second)]
    for chat_id, label in zip(chats, ("global", "first", "second")):
        database.save_turn(chat_id, "projectsecret", label + " projectsecret")
    asyncio.run(keeper.add_document("global.txt", b"projectsecret global"))
    asyncio.run(keeper.add_document("first.txt", b"projectsecret first", first))
    asyncio.run(keeper.add_document("second.txt", b"projectsecret second", second))
    database.add_memory("projectsecret personal fact", None)
    from cerberus import tools
    for project, label in ((None, "global"), (first, "first"), (second, "second")):
        current = database.create_chat("Current", project)["id"]
        found = asyncio.run(keeper.recall("projectsecret", keeper_mode=True, chat_id=current))
        assert [d["name"] for d in found["documents"]] == [label + ".txt"]
        assert {c["text"] for c in found["chats"]} == {"projectsecret", label + " projectsecret"}
        assert found["memories"] == ["projectsecret personal fact"]
        result = asyncio.run(tools.run_search_memory({"query": "projectsecret"}, tools.Context(chat_id=current)))
        for other in {"global", "first", "second"} - {label}:
            assert other + ".txt" not in result


def test_regenerate_invalidates_summary_and_recap(client):
    project = database.create_project("Project")["id"]
    chat_id = database.create_chat("Chat", project)["id"]
    database.save_turn(chat_id, "question", "answer")
    database.set_summary(chat_id, "old answer", 2)
    database.set_recap(project, chat_id, "old answer", 2)
    assert client.delete(f"/chats/{chat_id}/last-turn").status_code == 200
    assert database.get_summary(chat_id) is None
    assert database.get_recap(chat_id) is None


def test_budget_drops_complete_old_turns_and_preserves_new_question():
    messages = [{"role": "system", "content": "Personality"},
                {"role": "user", "content": "old" * 5000},
                {"role": "assistant", "content": "answer" * 2000},
                {"role": "user", "content": "Keep this question exactly"}]
    fitted = budget.fit(messages, 4600)
    assert fitted == [messages[0], messages[-1]]
    assert len(messages) == 4


def test_budget_accounts_for_images_tools_and_output():
    message = [{"role": "user", "content": "hello", "images": ["one", "two", "three", "four"]}]
    with pytest.raises(budget.ContextTooLarge):
        budget.fit(message, 4600)
    with pytest.raises(budget.ContextTooLarge):
        budget.fit([{"role": "user", "content": "hello"}], 600, [{"description": "x" * 30000}])


def test_oversized_current_question_returns_actionable_error(client):
    response = client.post("/chat", json=request(messages=[{"role": "user", "content": "x" * 40000}]))
    assert response.status_code == 413
    assert "Shorten" in response.json()["detail"]


def test_backup_contains_restorable_snapshot_documents_and_exports(client, tmp_path, monkeypatch):
    monkeypatch.setattr(keeper, "DOCUMENTS_DIR", str(tmp_path / "documents"))
    doc = asyncio.run(keeper.add_document("notes.txt", b"a private document"))
    chat_id = database.create_chat("My chat")["id"]
    database.save_turn(chat_id, "Question", "Answer")
    response = client.get("/backup")
    assert response.status_code == 200
    with ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read("documents.json"))
        assert manifest[0]["id"] == doc["id"]
        assert archive.read(manifest[0]["archive_path"]) == b"a private document"
        assert b"Stop Cerberus" in archive.read("RESTORE.txt")
        restored = tmp_path / "restored.db"
        restored.write_bytes(archive.read("cerberus.db"))
    with sqlite3.connect(restored) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT content FROM messages ORDER BY id").fetchall() == [("Question",), ("Answer",)]
    assert client.get(f"/chats/{chat_id}/export?format=json").json()["title"] == "My chat"
    markdown = client.get(f"/chats/{chat_id}/export").text
    assert "# My chat" in markdown and "## You" in markdown and "Answer" in markdown
    assert client.get("/chats/999/export").status_code == 404


def test_backup_does_not_silently_omit_missing_document(client):
    database.add_document("lost.txt", "/does-not-exist/cerberus-document.txt")
    assert client.get("/backup").status_code == 409


def test_migration_preserves_existing_documents_and_is_repeatable(db):
    document_id = database.add_document("existing.txt", "documents/existing.txt")
    with database.get_db() as conn:
        conn.execute("ALTER TABLE documents DROP COLUMN project_id")
    database.init_db()
    database.init_db()
    assert database.list_documents()[0]["id"] == document_id
