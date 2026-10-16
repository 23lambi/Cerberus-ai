import sqlite3
from contextlib import contextmanager
from datetime import datetime

from cerberus.config import DB_PATH


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript("""
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    embedding TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    text TEXT NOT NULL,
    embedding TEXT
);

CREATE TABLE IF NOT EXISTS summaries (
    chat_id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    covered INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);


-- UNIQUE: each chat has one recap. File notes (Step 3) have no chat_id.
CREATE TABLE IF NOT EXISTS project_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    chat_id INTEGER UNIQUE,
    kind TEXT NOT NULL DEFAULT 'recap',
    text TEXT NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
""")
        # Your database already has a chats table, and CREATE TABLE IF NOT EXISTS
        # won't change it. So we add the new column by hand, only if it's missing.
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(chats)")]
        if "project_id" not in columns:
            conn.execute("ALTER TABLE chats ADD COLUMN project_id INTEGER")


def now():
    return datetime.now().isoformat(timespec="seconds")


# ---------- Chats ----------


def create_chat(title, project_id=None):
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO chats (title, created_at, project_id) VALUES (?, ?, ?)",
            (title, now(), project_id),
        )
    return {"id": cursor.lastrowid, "title": title, "project_id": project_id}


def list_chats(project_id=None):
    # No project: the normal chats. With a project: only that project's chats.
    with get_db() as conn:
        if project_id is None:
            rows = conn.execute(
                "SELECT id, title, created_at FROM chats "
                "WHERE project_id IS NULL ORDER BY id DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, created_at FROM chats "
                "WHERE project_id = ? ORDER BY id DESC",
                (project_id,),
            ).fetchall()
    return [dict(row) for row in rows]


def get_chat(chat_id):
    with get_db() as conn:
        chat = conn.execute(
            "SELECT id, title, project_id FROM chats WHERE id = ?", (chat_id,)
        ).fetchone()
        if chat is None:
            return None
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id",
            (chat_id,),
        ).fetchall()
    return {
        "id": chat["id"],
        "title": chat["title"],
        "project_id": chat["project_id"],
        "messages": [dict(row) for row in rows],
    }


def delete_chat(chat_id):
    with get_db() as conn:
        conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM summaries WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM project_notes WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))


def set_chat_title(chat_id, title):
    with get_db() as conn:
        conn.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))


def get_summary(chat_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT text, covered FROM summaries WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    return dict(row) if row else None


def set_summary(chat_id, text, covered):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO summaries (chat_id, text, covered) VALUES (?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET "
            "text = excluded.text, covered = excluded.covered",
            (chat_id, text, covered),
        )


def save_message(chat_id, role, content):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages (chat_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, role, content, now()),
        )
        if role == "user":
            conn.execute(
                "UPDATE chats SET title = ? WHERE id = ? AND title = 'New chat'",
                (content[:40], chat_id),
            )


# ---------- Projects ----------


def create_project(name):
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO projects (name, created_at) VALUES (?, ?)", (name, now())
        )
    return {"id": cursor.lastrowid, "name": name}


def list_projects():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT p.id, p.name, p.created_at, COUNT(c.id) AS chats "
            "FROM projects p LEFT JOIN chats c ON c.project_id = p.id "
            "GROUP BY p.id ORDER BY p.id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def rename_project(project_id, name):
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE projects SET name = ? WHERE id = ?", (name, project_id)
        )
    return cursor.rowcount > 0


def delete_project(project_id):
    # A project takes its chats, their messages and their summaries with it.
    with get_db() as conn:
        chat_ids = "SELECT id FROM chats WHERE project_id = ?"
        conn.execute(f"DELETE FROM messages WHERE chat_id IN ({chat_ids})", (project_id,))
        conn.execute(f"DELETE FROM summaries WHERE chat_id IN ({chat_ids})", (project_id,))
        conn.execute("DELETE FROM project_notes WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM chats WHERE project_id = ?", (project_id,))
        cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    return cursor.rowcount > 0

def get_project(project_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, name FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    return dict(row) if row else None


# ---------- Project notes ----------


def set_recap(project_id, chat_id, text, message_count):
    # Insert or update, like set_summary: a chat only ever has one recap.
    with get_db() as conn:
        conn.execute(
            "INSERT INTO project_notes "
            "(project_id, chat_id, kind, text, message_count, updated_at) "
            "VALUES (?, ?, 'recap', ?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET text = excluded.text, "
            "message_count = excluded.message_count, updated_at = excluded.updated_at",
            (project_id, chat_id, text, message_count, now()),
        )


def get_recap(chat_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT text, message_count FROM project_notes WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
    return dict(row) if row else None


def project_notes(project_id, exclude_chat_id=None):
    # Newest first. c.title is the chat's title; notes without a chat get None.
    sql = (
        "SELECT n.id, n.chat_id, n.kind, n.text, n.updated_at, c.title "
        "FROM project_notes n LEFT JOIN chats c ON c.id = n.chat_id "
        "WHERE n.project_id = ?"
    )
    params = [project_id]
    if exclude_chat_id:
        # "chat_id IS NULL OR" keeps notes that don't belong to any chat.
        sql += " AND (n.chat_id IS NULL OR n.chat_id != ?)"
        params.append(exclude_chat_id)
    sql += " ORDER BY n.updated_at DESC, n.id DESC"

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]
# ---------- Settings ----------


def get_setting(key):
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else None


def set_setting(key, value):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def clear_settings():
    with get_db() as conn:
        conn.execute("DELETE FROM settings")


# ---------- Memories ----------


def add_memory(text, embedding):
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO memories (text, embedding, created_at) VALUES (?, ?, ?)",
            (text, embedding, now()),
        )
    return {"id": cursor.lastrowid, "text": text}


def list_memories():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, text, created_at FROM memories ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def memories_with_embeddings():
    with get_db() as conn:
        rows = conn.execute("SELECT id, text, embedding FROM memories").fetchall()
    return [dict(row) for row in rows]


def update_memory(memory_id, text, embedding):
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE memories SET text = ?, embedding = ? WHERE id = ?",
            (text, embedding, memory_id),
        )
    return cursor.rowcount > 0


def delete_memory(memory_id):
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    return cursor.rowcount > 0


# ---------- Documents ----------


def add_document(name, path):
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO documents (name, path, created_at) VALUES (?, ?, ?)",
            (name, path, now()),
        )
    return cursor.lastrowid


def add_chunks(document_id, chunks):
    with get_db() as conn:
        conn.executemany(
            "INSERT INTO chunks (document_id, position, text, embedding) "
            "VALUES (?, ?, ?, ?)",
            [(document_id, pos, text, emb) for pos, text, emb in chunks],
        )


def list_documents():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT d.id, d.name, d.created_at, COUNT(c.id) AS chunks "
            "FROM documents d LEFT JOIN chunks c ON c.document_id = d.id "
            "GROUP BY d.id ORDER BY d.id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def all_chunks():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT c.text, c.embedding, d.name FROM chunks c "
            "JOIN documents d ON d.id = c.document_id"
        ).fetchall()
    return [dict(row) for row in rows]


def delete_document(document_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT path FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    return row["path"]


# ---------- Searching old chats ----------


def search_messages(words, exclude_chat_id=None, limit=200):
    # Only the structure of the SQL is built here; every value
    # still goes through a ? placeholder.
    conditions = " OR ".join("m.content LIKE ?" for _ in words)
    params = [f"%{word}%" for word in words]
    sql = (
        "SELECT m.role, m.content, m.created_at, c.title FROM messages m "
        f"JOIN chats c ON c.id = m.chat_id WHERE ({conditions})"
    )
    if exclude_chat_id:
        sql += " AND m.chat_id != ?"
        params.append(exclude_chat_id)
    sql += " ORDER BY m.id DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]
