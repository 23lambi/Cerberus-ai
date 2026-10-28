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
from pathlib import Path

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


def snapshot(path):
    """SQLite's backup API makes a consistent copy, including WAL changes."""
    with get_db() as source, sqlite3.connect(path) as target:
        source.backup(target)
        target.row_factory = sqlite3.Row
        return [dict(row) for row in target.execute("SELECT id, path FROM documents")]


def init_db():
    # A new install: the data folder (see config.data_dir) may not exist yet.
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    # CREATE TABLE IF NOT EXISTS does nothing when the table is already there,
    # so this is safe to run every time the server starts.
    with get_db() as conn:
        # WAL ("write-ahead log"): a save goes to cerberus.db-wal first, so
        # reading never has to wait for a save to finish, and the other way
        # round. The setting is stored in the database file itself.
        conn.execute("PRAGMA journal_mode=WAL")
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
        if "sources" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN sources TEXT")
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(documents)")]
        if "project_id" not in columns:
            conn.execute("ALTER TABLE documents ADD COLUMN project_id INTEGER")
        for column, definition in (("content", "TEXT"), ("revision", "INTEGER NOT NULL DEFAULT 0"), ("chat_id", "INTEGER")):
            if column not in columns:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {column} {definition}")
        conn.executescript("""
CREATE TABLE IF NOT EXISTS document_versions (
    document_id INTEGER NOT NULL, revision INTEGER NOT NULL,
    name TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY (document_id, revision)
);
CREATE TABLE IF NOT EXISTS document_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL,
    revision INTEGER NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
);
""")

        # Indexes: like the index at the back of a book. Without one, finding
        # "the messages of chat 7" means reading every message of every chat.
        # With one, SQLite jumps straight to them. They come last, because
        # some of these columns are only added by the migrations above.
        conn.executescript("""
CREATE INDEX IF NOT EXISTS messages_by_chat ON messages (chat_id);
CREATE INDEX IF NOT EXISTS chats_by_project ON chats (project_id);
CREATE INDEX IF NOT EXISTS chunks_by_document ON chunks (document_id);
CREATE INDEX IF NOT EXISTS documents_by_project ON documents (project_id);
CREATE INDEX IF NOT EXISTS documents_by_chat ON documents (chat_id);
CREATE INDEX IF NOT EXISTS notes_by_project ON project_notes (project_id);
""")


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
            "SELECT role, content, images, seen, sources FROM messages WHERE chat_id = ? ORDER BY id",
            (chat_id,),
        ).fetchall()
    return {
        "id": chat["id"],
        "title": chat["title"],
        "project_id": chat["project_id"],
        "sources": {str(i): json.loads(row["sources"]) for i, row in enumerate(rows) if row["sources"]},
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


def get_chat_info(chat_id):
    # Only the chat itself (id, title, project_id), without its messages.
    # Much cheaper than get_chat when a chat has many messages or images.
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, title, project_id FROM chats WHERE id = ?", (chat_id,)
        ).fetchone()
    return dict(row) if row else None


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
        conn.execute("DELETE FROM summaries WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM project_notes WHERE chat_id = ?", (chat_id,))
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


def save_turn(chat_id, question, reply, images=None, seen="", expected_count=0, sources=None):
    """Commit both messages together, only if the chat still has the same history."""
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM chats WHERE id = ?", (chat_id,)).fetchone() is None:
            return False
        count = conn.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ?", (chat_id,)).fetchone()[0]
        if count != expected_count:
            return False
        conn.executemany(
            "INSERT INTO messages (chat_id, role, content, images, seen, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [(chat_id, "user", question, json.dumps(images) if images else None, seen or None, now()),
             (chat_id, "assistant", reply, None, None, now())],
        )
        if sources:
            conn.execute("UPDATE messages SET sources = ? WHERE id = (SELECT MAX(id) FROM messages WHERE chat_id = ?)",
                         (json.dumps(sources), chat_id))
        conn.execute("UPDATE chats SET title = ? WHERE id = ? AND title = 'New chat'", (question[:40], chat_id))
    return True


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


def add_document(name, path, project_id=None, chat_id=None):
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO documents (name, path, created_at, project_id, chat_id) VALUES (?, ?, ?, ?, ?)",
            (name, path, now(), project_id, chat_id),
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


def list_documents(project_id=None):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT d.id, d.name, d.created_at, d.project_id, d.revision, "
            "(d.content IS NOT NULL) AS editable, COUNT(c.id) AS chunks "
            "FROM documents d LEFT JOIN chunks c ON c.document_id = d.id "
            "WHERE d.project_id IS ? AND d.chat_id IS NULL GROUP BY d.id ORDER BY d.id DESC", (project_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def all_chunks(project_id=None):
    # Every chunk, with the name of the document it came from.
    with get_db() as conn:
        rows = conn.execute(
            "SELECT c.text, c.embedding, d.name, d.id AS document_id, d.revision, c.position FROM chunks c "
            "JOIN documents d ON d.id = c.document_id WHERE d.project_id IS ? AND d.chat_id IS NULL", (project_id,)
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
        conn.execute("DELETE FROM document_versions WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM document_proposals WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    return row["path"]


def get_document(document_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    return dict(row) if row else None


def write_document(name, content, project_id, chunks, document_id=None, revision=None):
    """Save content, history and retrieval chunks together; reject stale edits."""
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if document_id is None:
            if project_id is not None and not conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
                raise ValueError("Project no longer exists")
            cursor = conn.execute(
                "INSERT INTO documents (name, path, created_at, project_id, content, revision) VALUES (?, '', ?, ?, ?, 1)",
                (name, now(), project_id, content))
            document_id, next_revision = cursor.lastrowid, 1
        else:
            next_revision = revision + 1
            cursor = conn.execute(
                "UPDATE documents SET name = ?, content = ?, revision = ? "
                "WHERE id = ? AND revision = ? AND content IS NOT NULL",
                (name, content, next_revision, document_id, revision))
            if not cursor.rowcount:
                raise ValueError("Document changed or was removed. Reopen it before saving.")
        conn.execute("INSERT INTO document_versions VALUES (?, ?, ?, ?, ?)",
                     (document_id, next_revision, name, content, now()))
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        conn.executemany("INSERT INTO chunks (document_id, position, text, embedding) VALUES (?, ?, ?, ?)",
                         [(document_id, *chunk) for chunk in chunks])
    return get_document(document_id)


def document_versions(document_id):
    with get_db() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT revision, name, content, created_at FROM document_versions WHERE document_id = ? ORDER BY revision DESC",
            (document_id,))]


def add_proposal(document_id, revision, content):
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO document_proposals (document_id, revision, content, created_at) "
            "SELECT id, revision, ?, ? FROM documents WHERE id = ? AND revision = ? AND content IS NOT NULL",
            (content, now(), document_id, revision))
        if not cursor.rowcount:
            raise ValueError("Document changed or was removed. Reopen it before proposing edits.")
        return cursor.lastrowid


def get_proposal(document_id, proposal_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM document_proposals WHERE id = ? AND document_id = ?",
                           (proposal_id, document_id)).fetchone()
    return dict(row) if row else None


# ---------- Searching old chats ----------


def search_messages(words, exclude_chat_id=None, limit=200, project_id=None):
    # Only the structure of the SQL is built here; every value
    # still goes through a ? placeholder.
    # For ["python", "loop"] this builds: m.content LIKE ? OR m.content LIKE ?
    # and "%python%" means "python anywhere in the text".
    if not words:
        return []
    conditions = " OR ".join("m.content LIKE ? ESCAPE '\\'" for _ in words)
    params = [like_pattern(word) for word in words]
    sql = (
        "SELECT m.role, m.content, m.created_at, c.title FROM messages m "
        f"JOIN chats c ON c.id = m.chat_id WHERE ({conditions}) AND c.project_id IS ?"
    )
    params.append(project_id)
    if exclude_chat_id:
        sql += " AND m.chat_id != ?"
        params.append(exclude_chat_id)
    sql += " ORDER BY m.id DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def chat_documents(chat_id):
    with get_db() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM documents WHERE chat_id = ? ORDER BY id", (chat_id,))]
