"""Workspace saves, search, review/apply, history and backup use real SQLite."""

import io
import sqlite3
from zipfile import ZipFile

import pytest

from cerberus import database, keeper, ollama


def create(client, **values):
    response = client.post("/documents/workspace", json={
        "name": "notes.md", "content": "Original aardvark notes", **values})
    assert response.status_code == 200, response.text
    return response.json()


def edit(client, doc, content, **values):
    return client.put(f"/documents/{doc['id']}", json={
        "name": doc["name"], "content": content, "revision": doc["revision"],
        "project_id": doc["project_id"], **values})


def propose(client, doc):
    return client.post(f"/documents/{doc['id']}/proposals", json={
        "instruction": "Rewrite the introduction", "model": "small:3b", "revision": doc["revision"]})


def test_workspace_scope_versions_and_reindex(client):
    project = database.create_project("One")["id"]
    other = database.create_project("Two")["id"]
    doc = create(client, project_id=project)
    assert doc["revision"] == 1
    assert client.get("/documents").json()["documents"] == []
    assert client.get(f"/documents?project_id={other}").json()["documents"] == []
    listed = client.get(f"/documents?project_id={project}").json()["documents"]
    assert listed[0]["editable"] and listed[0]["id"] == doc["id"]
    assert database.all_chunks(other) == []
    updated = edit(client, doc, "Replaced zebra notes").json()
    assert updated["revision"] == 2
    assert [c["text"] for c in database.all_chunks(project)] == ["Replaced zebra notes"]
    versions = client.get(f"/documents/{doc['id']}/versions").json()["versions"]
    assert [v["revision"] for v in versions] == [2, 1]
    assert versions[1]["content"] == doc["content"]
    restored = edit(client, updated, versions[1]["content"]).json()
    assert restored["revision"] == 3 and restored["content"] == doc["content"]


def test_stale_save_and_project_move_cannot_overwrite(client):
    doc = create(client)
    assert edit(client, doc, "Newer text").status_code == 200
    assert edit(client, doc, "Stale text").status_code == 409
    project = database.create_project("Another")["id"]
    assert edit(client, doc, "Move", project_id=project).status_code == 400
    assert database.get_document(doc["id"])["content"] == "Newer text"


def test_proposal_changes_nothing_until_apply_and_only_applies_once(client, fake):
    doc = create(client)
    fake.reply = "Revised introduction"
    response = propose(client, doc)
    assert response.status_code == 200
    proposal = response.json()
    assert "-Original" in proposal["diff"] and "+Revised" in proposal["diff"]
    assert database.get_document(doc["id"])["content"] == doc["content"]
    url = f"/documents/{doc['id']}/proposals/{proposal['id']}/apply"
    assert client.post(url).json()["content"] == fake.reply
    assert client.post(url).status_code == 409
    assert len(database.document_versions(doc["id"])) == 2


def test_stale_proposal_and_wrong_document_are_rejected(client):
    doc = create(client)
    proposal = propose(client, doc).json()
    other = create(client)
    assert client.post(f"/documents/{other['id']}/proposals/{proposal['id']}/apply").status_code == 404
    assert edit(client, doc, "New manual edit").status_code == 200
    assert client.post(f"/documents/{doc['id']}/proposals/{proposal['id']}/apply").status_code == 409
    assert propose(client, doc).status_code == 409
    assert database.get_document(doc["id"])["content"] == "New manual edit"


@pytest.mark.parametrize("reply,cut_off", [("", False), ("Partial revision", True)])
def test_unusable_model_output_never_becomes_a_proposal(client, monkeypatch, reply, cut_off):
    doc = create(client)

    async def output(*args, **kwargs):
        yield "content", reply
        yield "stats", {"cut_off": cut_off}

    monkeypatch.setattr(ollama, "stream_events", output)
    assert propose(client, doc).status_code == 422
    with database.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM document_proposals").fetchone()[0] == 0
    assert database.get_document(doc["id"])["revision"] == 1


def test_proposal_failure_and_context_limit_preserve_document(client, monkeypatch):
    doc = create(client)

    async def failure(*args, **kwargs):
        raise ollama.OllamaError("Model unavailable")
        yield

    monkeypatch.setattr(ollama, "stream_events", failure)
    assert propose(client, doc).status_code == 502
    large = create(client, content="x" * 30000)
    assert propose(client, large).status_code == 413
    assert database.get_document(doc["id"])["revision"] == 1


def test_document_changed_during_generation_rejects_proposal(client, monkeypatch):
    doc = create(client)

    async def output(*args, **kwargs):
        database.write_document(doc["name"], "Concurrent save", None, [], doc["id"], 1)
        yield "content", "Outdated model edit"

    monkeypatch.setattr(ollama, "stream_events", output)
    assert propose(client, doc).status_code == 409
    assert database.get_document(doc["id"])["content"] == "Concurrent save"


def test_failed_index_write_rolls_back_content_and_history(client):
    doc = create(client)
    with database.get_db() as conn:
        conn.execute("CREATE TRIGGER fail_chunk BEFORE INSERT ON chunks BEGIN SELECT RAISE(ABORT, 'failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        database.write_document("changed.md", "changed", None, [(0, "changed", None)], doc["id"], 1)
    assert database.get_document(doc["id"])["content"] == doc["content"]
    assert len(database.document_versions(doc["id"])) == 1
    assert database.all_chunks()[0]["text"] == doc["content"]


def test_workspace_backup_includes_content_and_versions(client, tmp_path):
    doc = create(client)
    edit(client, doc, "Second version")
    response = client.get("/backup")
    assert response.status_code == 200
    with ZipFile(io.BytesIO(response.content)) as archive:
        path = tmp_path / "restored.db"
        path.write_bytes(archive.read("cerberus.db"))
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT content FROM documents").fetchone()[0] == "Second version"
        assert conn.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0] == 2


def test_uploaded_files_can_be_read_and_copied_without_overwriting_original(client, tmp_path, monkeypatch):
    monkeypatch.setattr(keeper, "DOCUMENTS_DIR", str(tmp_path))
    uploaded = client.post("/documents?name=original.txt", content=b"Original file text").json()
    read = client.get(f"/documents/{uploaded['id']}").json()
    assert read["content"] == "Original file text" and not read["editable"]
    assert edit(client, read, "Attempt overwrite").status_code == 400
    copied = create(client, content=read["content"])
    assert copied["id"] != read["id"]
    assert client.get(f"/documents/{read['id']}").json()["content"] == read["content"]


def test_project_deletion_removes_workspace_history_and_proposals(client):
    project = database.create_project("Disposable")["id"]
    doc = create(client, project_id=project)
    propose(client, doc)
    assert client.delete(f"/projects/{project}").status_code == 200
    assert client.get(f"/documents/{doc['id']}").status_code == 404
    with database.get_db() as conn:
        for table in ("documents", "chunks", "document_versions", "document_proposals"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("name", [" ", "notes.txt", "../notes.md", "/notes.md"])
def test_invalid_workspace_names(client, name):
    assert client.post("/documents/workspace", json={"name": name, "content": "text"}).status_code == 422


def test_missing_project_and_empty_document(client):
    assert client.post("/documents/workspace", json={"name": "x.md", "content": "", "project_id": 999}).status_code == 404
    doc = create(client, content="")
    assert database.all_chunks() == []
    assert doc["revision"] == 1
    database.init_db()
    assert database.get_document(doc["id"])["content"] == ""
