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
""")


def now():
    return datetime.now().isoformat(timespec="seconds")


def create_chat(title):
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO chats (title, created_at) VALUES (?, ?)",
            (title, now()),
        )
    return {"id": cursor.lastrowid, "title": title}


def list_chats():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at FROM chats ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_chat(chat_id):
    with get_db() as conn:
        chat = conn.execute(
            "SELECT id, title FROM chats WHERE id = ?", (chat_id,)
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
        "messages": [dict(row) for row in rows],
    }


def delete_chat(chat_id):
    with get_db() as conn:
        conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))

def set_chat_title(chat_id,title):
    with get_db() as conn:
        conn.execute("UPDATE chats SET title = ? WHERE id = ?",(title,chat_id))

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
