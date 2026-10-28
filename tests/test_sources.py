"""Citations carry actual prompt evidence and survive editing and deletion."""

import json

import pytest

from cerberus import database, keeper


def ask(client, chat_id, route="/chat"):
    history = database.get_chat(chat_id)["messages"]
    response = client.post(route, json={"chat_id": chat_id, "model": "small:3b",
        "messages": history + [{"role": "user", "content": "What does the document say?"}]})
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines()]


@pytest.mark.parametrize("route", ["/chat", "/council"])
def test_attachment_sources_are_streamed_and_saved_with_the_answer(client, fake, tmp_path, monkeypatch, route):
    monkeypatch.setattr(keeper, "DOCUMENTS_DIR", str(tmp_path))
    chat = database.create_chat("Sources")["id"]
    doc = client.post(f"/documents?name=evidence.txt&chat_id={chat}", content=b"The access code is ORCHID.").json()
    fake.reply = "The access code is ORCHID [1]."
    events = ask(client, chat, route)
    assert events[0]["type"] == "sources"
    source = events[0]["sources"][0]
    assert source["number"] == 1 and source["document_id"] == doc["id"]
    assert source["text"] == "The access code is ORCHID."
    assert "[1] evidence.txt" in fake.calls[-1]["messages"][-1]["content"] or route == "/council"
    saved = client.get(f"/chats/{chat}").json()
    assert saved["sources"]["1"] == [source]
    # Snapshot metadata is separate from message history, preserving stale-history checks.
    ask(client, chat, route)
    assert len(database.get_chat(chat)["messages"]) == 4
    assert client.delete(f"/documents/{doc['id']}").status_code == 200
    assert client.get(f"/documents/{doc['id']}").status_code == 404
    assert client.get(f"/chats/{chat}").json()["sources"]["1"][0]["text"] == source["text"]
    assert "sources" in client.get(f"/chats/{chat}/export?format=json").json()


def test_retrieved_passage_snapshot_keeps_id_position_and_original_revision(client, fake):
    project = database.create_project("Evidence")["id"]
    other = database.create_project("Other")["id"]
    doc = client.post("/documents/workspace", json={"name": "orchid.md", "content": "orchid evidence orchid", "project_id": project}).json()
    chat = database.create_chat("Search", project)["id"]
    response = client.post('/chat', json={"chat_id": chat, "model": "small:3b",
        "messages": [{"role": "user", "content": "orchid"}]})
    assert response.status_code == 200
    source = database.get_chat(chat)["sources"]["1"][0]
    assert source["document_id"] == doc["id"]
    assert source["position"] == 0 and source["revision"] == 1
    client.put(f"/documents/{doc['id']}", json={"name": doc["name"], "content": "Edited away", "project_id": project, "revision": 1})
    assert database.get_chat(chat)["sources"]["1"][0]["text"] == "orchid evidence orchid"
    private_chat = database.create_chat("Other", other)["id"]
    events = ask(client, private_chat)
    assert all(event["type"] != "sources" for event in events)


def test_preview_returns_text_without_server_file_path(client, tmp_path, monkeypatch):
    monkeypatch.setattr(keeper, "DOCUMENTS_DIR", str(tmp_path))
    doc = client.post('/documents?name=unsafe.html', content=b'<script>bad()</script>').json()
    preview = client.get(f"/documents/{doc['id']}")
    assert preview.status_code == 200
    assert preview.json()["content"] == "<script>bad()</script>"
    assert "path" not in preview.json()
