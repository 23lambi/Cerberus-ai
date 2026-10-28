"""Chat uploads are private to that chat and included without a search match."""
from pathlib import Path

from cerberus.storage import database, keeper
from cerberus.chat import turns


def test_chat_file_is_direct_context_and_not_shared(client, fake, tmp_path, monkeypatch):
    monkeypatch.setattr(keeper, "DOCUMENTS_DIR", str(tmp_path))
    project = database.create_project("Project")["id"]
    chat = database.create_chat("Attached", project)["id"]
    other = database.create_chat("Other", project)["id"]
    uploaded = client.post(f"/documents?name=letter.txt&chat_id={chat}", content=b"The secret code is ORCHID.")
    assert uploaded.status_code == 200
    assert database.all_chunks(project) == []
    assert client.get(f"/documents?project_id={project}").json()["documents"] == []
    assert len(client.get(f"/chats/{chat}").json()["documents"]) == 1
    for chat_id in (chat, other):
        response = client.post('/chat', json={"chat_id": chat_id, "model": "small:3b",
            "messages": [{"role": "user", "content": "What does this say?"}]})
        assert response.status_code == 200
        sent = fake.calls[-1]["messages"][-1]["content"]
        assert ("ORCHID" in sent) == (chat_id == chat)
    assert "ORCHID" not in database.get_chat(chat)["messages"][0]["content"]
    path = Path(database.chat_documents(chat)[0]["path"])
    assert client.delete(f"/chats/{chat}").status_code == 200
    assert not path.exists()
    assert database.chat_documents(chat) == []


def test_missing_or_active_chat_cannot_receive_file(client):
    assert client.post('/documents?name=x.txt&chat_id=999', content=b'text').status_code == 404
    chat = database.create_chat("Busy")["id"]
    turns.active[chat] = object()
    try:
        assert client.post(f'/documents?name=x.txt&chat_id={chat}', content=b'text').status_code == 409
    finally:
        turns.active.pop(chat)


def test_project_deletion_removes_chat_attachments(client, tmp_path, monkeypatch):
    monkeypatch.setattr(keeper, "DOCUMENTS_DIR", str(tmp_path))
    project = database.create_project("Disposable")["id"]
    chat = database.create_chat("Chat", project)["id"]
    client.post(f"/documents?name=x.txt&chat_id={chat}", content=b"private attachment")
    path = Path(database.chat_documents(chat)[0]["path"])
    assert client.delete(f"/projects/{project}").status_code == 200
    assert not path.exists()
    assert database.chat_documents(chat) == []
