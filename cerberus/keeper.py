# The Keeper is Cerberus's long-term memory. It keeps three kinds of things:
#   - memories: short facts about the user ("I study computer science")
#   - documents: uploaded files, cut into chunks
#   - old chats: earlier messages, found by keyword search
# recall() searches all three and returns what fits the user's question.
#
# How "search by meaning" works: an embedding model turns each text into a
# vector (a long list of numbers). Texts with similar meaning get vectors
# that point in a similar direction, and cosine() measures that direction.

import io
import json
import math
import re
from pathlib import Path
from uuid import uuid4

from cerberus import database
from cerberus.config import (
    CHAT_SEARCH_RESULTS,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    DOC_MIN_SCORE,
    DOC_RESULTS,
    DOCUMENTS_DIR,
    KEEPER_DOC_MIN_SCORE,
    KEEPER_DOC_RESULTS,
    KEEPER_MIN_SCORE,
    KEEPER_RESULTS,
    MEMORY_MIN_SCORE,
    MEMORY_RESULTS,
)
from cerberus.ollama import OllamaError, embed

# Matches "remember that ...", "Please remember: ..." and captures the rest.
# (?:...) is a group that isn't captured, (.+) is the part we keep.
SAVE_PATTERN = re.compile(
    r"^\s*(?:please\s+)?remember(?:\s+that|\s*:)\s+(.+)$", re.IGNORECASE | re.DOTALL
)
TEXT_TYPES = {".txt", ".md", ".markdown", ".csv", ".json", ".py", ".js", ".html"}
# Common words that say nothing about the topic, so keyword search skips them.
STOP_WORDS = {
    "what", "when", "where", "which", "about", "that", "this", "have", "with",
    "your", "from", "they", "there", "were", "would", "could", "should", "tell",
    "know", "does", "said", "remember",
}


class DocumentError(Exception):
    # A problem with an uploaded file that the user should see,
    # like "this PDF is damaged". The route turns it into a 400 error.
    pass


def wants_to_save(message):
    # "Remember that I like tea." -> "I like tea", anything else -> None
    match = SAVE_PATTERN.match(message)
    if match is None:
        return None
    return match.group(1).strip().rstrip(".")


# ---------- Embeddings and scoring ----------


async def embed_texts(texts, kind):
    # nomic-embed-text works best with these prefixes:
    # "search_document: " for saved text, "search_query: " for questions.
    prefixed = [f"search_{kind}: {text}" for text in texts]
    vectors = []
    try:
        # Send 16 texts per request, so a big document doesn't make one huge request.
        for start in range(0, len(prefixed), 16):
            vectors += await embed(prefixed[start : start + 16])
    except OllamaError:
        # No embedding model: return one None per text. score() then
        # falls back to keyword matching.
        return [None] * len(texts)
    return vectors


async def embed_one(text, kind):
    return (await embed_texts([text], kind))[0]


def to_json(vector):
    # SQLite has no list type, so vectors are stored as JSON text.
    return json.dumps(vector) if vector else None


def cosine(a, b):
    # Cosine similarity: 1 = same direction (same meaning), 0 = unrelated.
    dot = sum(x * y for x, y in zip(a, b))
    size = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / size if size else 0.0


def words(text):
    # The set of words with 4+ letters, minus the stop words.
    return set(re.findall(r"\w{4,}", text.lower())) - STOP_WORDS


def score(query_vector, query_words, text, embedding):
    if query_vector and embedding:
        return cosine(query_vector, json.loads(embedding))
    # No embedding available: share of the question's words found in the text.
    if not query_words:
        return 0.0
    # "&" on sets = the words that are in both.
    return len(query_words & words(text)) / len(query_words)


def best(scored, limit, min_score):
    # scored is a list of (score, item). Keep the top `limit` that are good enough.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for value, item in scored[:limit] if value >= min_score]


# ---------- Memories ----------


def list_all():
    return database.list_memories()


async def add(text):
    vector = await embed_one(text, "document")
    return database.add_memory(text, to_json(vector))


async def update(memory_id, text):
    # New text means a new meaning, so the vector is made again too.
    vector = await embed_one(text, "document")
    return database.update_memory(memory_id, text, to_json(vector))


def delete(memory_id):
    return database.delete_memory(memory_id)


# ---------- Documents ----------


def read_text(name, data):
    # data is the raw bytes of the file. Returns the text inside it.
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        try:
            # Imported here, not at the top, so Cerberus still starts without pypdf.
            from pypdf import PdfReader
        except ImportError:
            raise DocumentError(
                "Reading PDFs needs pypdf. Install it with: pip install pypdf"
            ) from None
        try:
            # BytesIO makes the bytes look like a file, which is what PdfReader wants.
            reader = PdfReader(io.BytesIO(data))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            raise DocumentError("This PDF could not be read. It may be damaged.") from None
    if suffix in TEXT_TYPES:
        # errors="replace" turns broken bytes into "?" instead of crashing.
        return data.decode("utf-8", errors="replace")
    raise DocumentError("Cerberus can read .txt, .md, .pdf and code files.")


def split_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    # Cuts a long text into pieces of about `size` characters. Search works
    # on these pieces, so the model only gets the parts that matter.
    text = re.sub(r"\n{3,}", "\n\n", text).strip()  # squash big gaps
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # Prefer to cut at a paragraph, then a sentence, then a word.
            # Only look in the second half, so pieces don't get too small.
            for mark in ("\n\n", ". ", " "):
                cut = text.rfind(mark, start + size // 2, end)
                if cut != -1:
                    end = cut + len(mark)
                    break
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        # Step back by `overlap` so the next piece repeats the end of this one.
        # max(..., start + 1) makes sure we always move forward.
        start = max(end - overlap, start + 1)
    return chunks


async def add_document(name, data, project_id=None, chat_id=None):
    # Path(name).name drops any folders, so "../../x.txt" becomes "x.txt".
    name = Path(name).name
    text = read_text(name, data)
    if not text.strip():
        raise DocumentError(
            "No text found in this file. Scanned PDFs are images, not text."
        )

    # Keep a copy of the file. The random uuid prefix means two files with
    # the same name never overwrite each other, and the regex replaces
    # every unusual character with "_".
    folder = Path(DOCUMENTS_DIR)
    folder.mkdir(exist_ok=True)
    safe_name = re.sub(r"[^\w.\-]", "_", name)
    path = folder / f"{uuid4().hex[:8]}_{safe_name}"
    path.write_bytes(data)

    pieces = split_text(text)
    vectors = await embed_texts(pieces, "document")
    document_id = database.add_document(name, str(path), project_id, chat_id)
    database.add_chunks(
        document_id,
        # enumerate gives the position, zip pairs each piece with its vector.
        [(i, piece, to_json(v)) for i, (piece, v) in enumerate(zip(pieces, vectors))],
    )
    return {
        "id": document_id,
        "name": name,
        "chunks": len(pieces),
        "searchable_by_meaning": all(vectors),  # False if any vector is None
    }


def list_documents(project_id=None):
    return database.list_documents(project_id)


def delete_document(document_id):
    path = database.delete_document(document_id)
    if path is None:
        return False
    if path:
        Path(path).unlink(missing_ok=True)  # editable documents live in SQLite
    return True


# ---------- Old chats ----------


def search_chats(question, exclude_chat_id=None, project_id=None):
    # Old chat messages have no embeddings, so this is a keyword search:
    # SQL finds messages that contain any of the words, then we rank them
    # by how many of the words they contain.
    query_words = words(question)
    if not query_words:
        return []

    scored = []
    for row in database.search_messages(sorted(query_words), exclude_chat_id, project_id=project_id):
        hits = len(query_words & words(row["content"]))
        scored.append((hits, row))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    return [
        {
            "title": row["title"],
            "date": row["created_at"][:10],  # "2026-10-17T12:00:00" -> "2026-10-17"
            "role": row["role"],
            "text": row["content"][:300],
        }
        for hits, row in scored[:CHAT_SEARCH_RESULTS]
        if hits
    ]


# ---------- Recall: everything the Keeper knows about a question ----------


async def recall(question, keeper_mode=False, chat_id=None):
    chat = database.get_chat(chat_id) if chat_id else None
    project_id = chat["project_id"] if chat else None
    memory_rows = database.memories_with_embeddings()
    chunk_rows = database.all_chunks(project_id)

    # Only embed the question when there is something to compare it with.
    query_vector = None
    if memory_rows or chunk_rows:
        query_vector = await embed_one(question, "query")
    query_words = words(question)

    # Memory mode (the Guard said "memory") searches wider than normal chat.
    if keeper_mode:
        limits = (KEEPER_RESULTS, KEEPER_MIN_SCORE, KEEPER_DOC_RESULTS, KEEPER_DOC_MIN_SCORE)
    else:
        limits = (MEMORY_RESULTS, MEMORY_MIN_SCORE, DOC_RESULTS, DOC_MIN_SCORE)
    memory_limit, memory_min, doc_limit, doc_min = limits  # unpack the tuple

    memories = best(
        [(score(query_vector, query_words, r["text"], r["embedding"]), r["text"])
         for r in memory_rows],
        memory_limit,
        memory_min,
    )
    documents = best(
        [(score(query_vector, query_words, r["text"], r["embedding"]),
          {"name": r["name"], "text": r["text"], "document_id": r["document_id"],
           "revision": r["revision"], "position": r["position"]})
         for r in chunk_rows],
        doc_limit,
        doc_min,
    )
    chats = search_chats(question, chat_id, project_id) if keeper_mode else []

    return {"memories": memories, "documents": documents, "chats": chats}


def context_prompt(found):
    # Turns what recall() found into text for the system prompt.
    parts = []
    if found["memories"]:
        lines = "\n".join(f"- {m}" for m in found["memories"])
        parts.append(f"Things you know about the user, from long-term memory:\n{lines}")
    if found["documents"]:
        pieces = "\n\n".join(f"[{d['name']}]\n{d['text']}" for d in found["documents"])
        parts.append(f"Parts of the user's documents that may help:\n{pieces}")
    if found["chats"]:
        lines = "\n".join(
            f"[{c['title']}, {c['date']}] {c['role']}: {c['text']}" for c in found["chats"]
        )
        parts.append(f"Parts of earlier chats:\n{lines}")

    if not parts:
        return ""
    return (
        "\n\n".join(parts)
        + "\n\nUse this when it helps. Name the document when you use one."
        + " Don't list memories unless the user asks."
    )
