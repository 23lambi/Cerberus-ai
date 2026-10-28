# Tests for database.py. Every test asks for the "db" fixture from
# conftest.py, so it gets its own empty database in a temporary folder.

from cerberus.storage import database


def test_new_chat_is_listed(db):
    database.create_chat("First chat")
    assert [chat["title"] for chat in database.list_chats()] == ["First chat"]


def test_project_chats_stay_in_their_project(db):
    project = database.create_project("Thesis")
    database.create_chat("Normal chat")
    database.create_chat("Thesis chat", project["id"])

    assert [c["title"] for c in database.list_chats()] == ["Normal chat"]
    assert [c["title"] for c in database.list_chats(project["id"])] == ["Thesis chat"]


def test_search_finds_titles_and_messages(db):
    python = database.create_chat("Python loops")
    cooking = database.create_chat("Cooking")
    database.save_message(cooking["id"], "user", "A pasta recipe, please")

    assert [c["id"] for c in database.list_chats(query="python")] == [python["id"]]
    assert [c["id"] for c in database.list_chats(query="PASTA")] == [cooking["id"]]


def test_search_treats_percent_as_a_normal_character(db):
    chat = database.create_chat("Notes")
    database.save_message(chat["id"], "user", "The tax is 50% of it")

    assert len(database.list_chats(query="50%")) == 1
    assert database.list_chats(query="0%x") == []  # % is not "anything" here


def test_delete_last_turn_removes_question_and_answer(db):
    chat = database.create_chat("Chat")
    for role, text in [("user", "q1"), ("assistant", "a1"), ("user", "q2"), ("assistant", "a2")]:
        database.save_message(chat["id"], role, text)

    assert database.delete_last_turn(chat["id"]) is True
    messages = database.get_chat(chat["id"])["messages"]
    assert [m["content"] for m in messages] == ["q1", "a1"]


def test_first_question_becomes_the_title(db):
    chat = database.create_chat("New chat")
    database.save_message(chat["id"], "user", "How do I learn Rust?")
    assert database.get_chat(chat["id"])["title"] == "How do I learn Rust?"


def test_messages_are_found_by_index(db):
    # EXPLAIN QUERY PLAN asks SQLite HOW it would run a query, without
    # running it. "SCAN messages" = read the whole table, row by row;
    # "SEARCH messages USING INDEX" = jump straight to the right rows.
    with database.get_db() as conn:
        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM messages WHERE chat_id = ?", (1,)
        ).fetchall()
    steps = " ".join(row["detail"] for row in plan)
    assert "USING INDEX messages_by_chat" in steps


def test_database_uses_wal(db):
    # The mode is stored in the file, so every new connection gets it too.
    with database.get_db() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_snapshot_closes_both_database_handles(db, tmp_path, monkeypatch):
    """An open target prevents Windows from cleaning up the backup folder."""
    import sqlite3
    original_connect = sqlite3.connect
    connections = []

    class TrackedConnection(sqlite3.Connection):
        closed = False

        def close(self):
            self.closed = True
            return super().close()

    def connect(*args, **kwargs):
        connection = original_connect(*args, factory=TrackedConnection, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(database.sqlite3, "connect", connect)
    target = tmp_path / "snapshot.db"
    assert database.snapshot(target) == []
    assert len(connections) == 2
    assert all(connection.closed for connection in connections)
    target.unlink()
