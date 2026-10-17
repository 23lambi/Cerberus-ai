# All the SQL in Cerberus lives in this file. The rest of the code calls
# these functions and gets plain dicts and lists back, so it never has to
# know about tables or SQL.
#
# Safety rule used everywhere: values never go into the SQL text itself.
# They go in as "?" placeholders, and SQLite fills them in safely. That
# stops SQL injection (a message like "'; DROP TABLE chats; --").

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from cerberus.config import DB_PATH


# @contextmanager lets us write "with get_db() as conn:". The code before
# "yield" runs when the with-block starts, the code after it when it ends.
@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    # Row lets us read columns by name: row["title"] instead of row[1].
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()  # only save the changes if nothing went wrong
    finally:
        conn.close()  # always close, even after an error


def init_db():
    # CREATE TABLE IF NOT EXISTS does nothing when the table is already there,
    # so this is safe to run every time the server starts.
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
        # (Changing an existing database like this is called a "migration".)
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(chats)")]
        if "project_id" not in columns:
            conn.execute("ALTER TABLE chats ADD COLUMN project_id INTEGER")

        # The same for the images of a message (Level 10).
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(messages)")]
        if "images" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN images TEXT")
        if "seen" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN seen TEXT")


def now():
    # The time as text, like "2026-10-17T14:05:09". SQLite has no date type,
    # and this format sorts correctly as plain text.
    return datetime.now().isoformat(timespec="seconds")


# ---------- Chats ----------


def create_chat(title, project_id=None):
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO chats (title, created_at, project_id) VALUES (?, ?, ?)",
            (title, now(), project_id),
        )
    # lastrowid = the id SQLite just gave the new row.
    return {"id": cursor.lastrowid, "title": title, "project_id": project_id}


def like_pattern(text):
    # In LIKE, % means "any text" and _ means "any one letter". Someone
    # searching for "50%" or "my_file" means those characters literally,
    # so we put a \ in front of them (and of \ itself). The SQL then says
    # ESCAPE '\' to tell SQLite that \ is the escape character.
    text = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{text}%"


def list_chats(project_id=None, query=None):
    # No project: the normal chats. With a project: only that project's chats.
    # (In SQL you can't write "= NULL", you must write "IS NULL".)
    if project_id is None:
        sql = "SELECT id, title, created_at FROM chats c WHERE project_id IS NULL"
        params = []
    else:
        sql = "SELECT id, title, created_at FROM chats c WHERE project_id = ?"
        params = [project_id]

    if query:
        # A chat matches when its title or any of its messages contains the
        # text. EXISTS (...) is true when the inner SELECT finds at least one
        # row. LIKE ignores upper/lower case, but only for English letters.
        sql += (
            " AND (c.title LIKE ? ESCAPE '\\' OR EXISTS ("
            "SELECT 1 FROM messages m WHERE m.chat_id = c.id "
            "AND m.content LIKE ? ESCAPE '\\'))"
        )
        pattern = like_pattern(query)
        params += [pattern, pattern]

    sql += " ORDER BY id DESC"
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def get_chat(chat_id):
    # One chat with all its messages, oldest first. None if it doesn't exist.
    with get_db() as conn:
        chat = conn.execute(
            "SELECT id, title, project_id FROM chats WHERE id = ?", (chat_id,)
        ).fetchone()
        if chat is None:
            return None
        rows = conn.execute(
            "SELECT role, content, images, seen FROM messages WHERE chat_id = ? ORDER BY id",
            (chat_id,),
        ).fetchall()
    return {
        "id": chat["id"],
        "title": chat["title"],
        "project_id": chat["project_id"],
        # Images are stored as JSON text; turn them back into a list.
        "messages": [
            {
                "role": row["role"],
                "content": row["content"],
                "images": json.loads(row["images"]) if row["images"] else [],
                "seen": row["seen"] or "",
            }
            for row in rows
        ],
    }


def delete_chat(chat_id):
    # Delete everything that belongs to the chat first, then the chat itself.
    with get_db() as conn:
        conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM summaries WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM project_notes WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))


def delete_last_turn(chat_id):
    # Removes the newest question and its answer, for "Regenerate".
    # SQLite can't do "DELETE ... ORDER BY ... LIMIT", so a subquery picks
    # the ids of the two newest messages, and we delete those.
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM messages WHERE id IN ("
            "SELECT id FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT 2)",
            (chat_id,),
        )
    return cursor.rowcount > 0


def set_chat_title(chat_id, title):
    with get_db() as conn:
        cursor = conn.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))
    return cursor.rowcount > 0  # False = no chat with that id


def get_summary(chat_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT text, covered FROM summaries WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    return dict(row) if row else None


def set_summary(chat_id, text, covered):
    # An "upsert": INSERT a new row, or UPDATE it when this chat already
    # has one. "excluded" means the values we just tried to insert.
    with get_db() as conn:
        conn.execute(
            "INSERT INTO summaries (chat_id, text, covered) VALUES (?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET "
            "text = excluded.text, covered = excluded.covered",
            (chat_id, text, covered),
        )


def save_message(chat_id, role, content, images=None, seen=""):
    # images: a list of base64 pictures, saved as JSON text (None = no images).
    # seen: what the Eyes saw in them, so it never has to look twice.
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages (chat_id, role, content, images, seen, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                chat_id,
                role,
                content,
                json.dumps(images) if images else None,
                seen or None,
                now(),
            ),
        )
        if role == "user":
            # A first, quick title: the start of the first question.
            # The model writes a better one later (POST /chats/{id}/title).
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
    # LEFT JOIN keeps projects with no chats (COUNT is then 0).
    # GROUP BY p.id gives one row per project, with its chats counted.
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
    # rowcount = how many rows changed. 0 means no project had that id.
    return cursor.rowcount > 0


def delete_project(project_id):
    # A project takes its chats, their messages and their summaries with it.
    with get_db() as conn:
        # A subquery: "the ids of this project's chats", used inside IN (...).
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
    # Upsert: the key is the PRIMARY KEY, so a second save updates the row.
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
    # embedding is the vector as JSON text, or None when Ollama couldn't make one.
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO memories (text, embedding, created_at) VALUES (?, ?, ?)",
            (text, embedding, now()),
        )
    return {"id": cursor.lastrowid, "text": text}


def list_memories():
    # For the Memory panel: no embeddings, the browser doesn't need them.
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, text, created_at FROM memories ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def memories_with_embeddings():
    # For searching: here we do need the vectors.
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
    # executemany runs the same INSERT once per item: one row per chunk.
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
    # Every chunk, with the name of the document it came from.
    with get_db() as conn:
        rows = conn.execute(
            "SELECT c.text, c.embedding, d.name FROM chunks c "
            "JOIN documents d ON d.id = c.document_id"
        ).fetchall()
    return [dict(row) for row in rows]


def delete_document(document_id):
    # Returns the file's path, so keeper.py can delete the file too.
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
    # For ["python", "loop"] this builds: m.content LIKE ? OR m.content LIKE ?
    # and "%python%" means "python anywhere in the text".
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
