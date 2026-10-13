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

SAVE_PATTERN = re.compile(
    r"^\s*(?:please\s+)?remember(?:\s+that|\s*:)\s+(.+)$", re.IGNORECASE | re.DOTALL
)
TEXT_TYPES = {".txt", ".md", ".markdown", ".csv", ".json", ".py", ".js", ".html"}
STOP_WORDS = {
    "what", "when", "where", "which", "about", "that", "this", "have", "with",
    "your", "from", "they", "there", "were", "would", "could", "should", "tell",
    "know", "does", "said", "remember",
}


class DocumentError(Exception):
    pass


def wants_to_save(message):
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
        for start in range(0, len(prefixed), 16):
            vectors += await embed(prefixed[start : start + 16])
    except OllamaError:
        return [None] * len(texts)
    return vectors


async def embed_one(text, kind):
    return (await embed_texts([text], kind))[0]


def to_json(vector):
    return json.dumps(vector) if vector else None


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    size = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / size if size else 0.0


def words(text):
    return set(re.findall(r"\w{4,}", text.lower())) - STOP_WORDS


def score(query_vector, query_words, text, embedding):
    if query_vector and embedding:
        return cosine(query_vector, json.loads(embedding))
    # No embedding available: share of the question's words found in the text.
    if not query_words:
        return 0.0
    return len(query_words & words(text)) / len(query_words)


def best(scored, limit, min_score):
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for value, item in scored[:limit] if value >= min_score]


# ---------- Memories ----------


def list_all():
    return database.list_memories()


async def add(text):
    vector = await embed_one(text, "document")
    return database.add_memory(text, to_json(vector))


async def update(memory_id, text):
    vector = await embed_one(text, "document")
    return database.update_memory(memory_id, text, to_json(vector))


def delete(memory_id):
    return database.delete_memory(memory_id)


# ---------- Documents ----------


def read_text(name, data):
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise DocumentError(
                "Reading PDFs needs pypdf. Install it with: pip install pypdf"
            ) from None
        try:
            reader = PdfReader(io.BytesIO(data))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            raise DocumentError("This PDF could not be read. It may be damaged.") from None
    if suffix in TEXT_TYPES:
        return data.decode("utf-8", errors="replace")
    raise DocumentError("Cerberus can read .txt, .md, .pdf and code files.")


def split_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # Prefer to cut at a paragraph, then a sentence, then a word.
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
        start = max(end - overlap, start + 1)
    return chunks


async def add_document(name, data):
    name = Path(name).name
    text = read_text(name, data)
    if not text.strip():
        raise DocumentError(
            "No text found in this file. Scanned PDFs are images, not text."
        )

    folder = Path(DOCUMENTS_DIR)
    folder.mkdir(exist_ok=True)
    safe_name = re.sub(r"[^\w.\-]", "_", name)
    path = folder / f"{uuid4().hex[:8]}_{safe_name}"
    path.write_bytes(data)

    pieces = split_text(text)
    vectors = await embed_texts(pieces, "document")
    document_id = database.add_document(name, str(path))
    database.add_chunks(
        document_id,
        [(i, piece, to_json(v)) for i, (piece, v) in enumerate(zip(pieces, vectors))],
    )
    return {
        "id": document_id,
        "name": name,
        "chunks": len(pieces),
        "searchable_by_meaning": all(vectors),
    }


def list_documents():
    return database.list_documents()


def delete_document(document_id):
    path = database.delete_document(document_id)
    if path is None:
        return False
    Path(path).unlink(missing_ok=True)
    return True


# ---------- Old chats ----------


def search_chats(question, exclude_chat_id=None):
    query_words = words(question)
    if not query_words:
        return []

    scored = []
    for row in database.search_messages(sorted(query_words), exclude_chat_id):
        hits = len(query_words & words(row["content"]))
        scored.append((hits, row))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    return [
        {
            "title": row["title"],
            "date": row["created_at"][:10],
            "role": row["role"],
            "text": row["content"][:300],
        }
        for hits, row in scored[:CHAT_SEARCH_RESULTS]
        if hits
    ]


# ---------- Recall: everything the Keeper knows about a question ----------


async def recall(question, keeper_mode=False, chat_id=None):
    memory_rows = database.memories_with_embeddings()
    chunk_rows = database.all_chunks()

    query_vector = None
    if memory_rows or chunk_rows:
        query_vector = await embed_one(question, "query")
    query_words = words(question)

    if keeper_mode:
        limits = (KEEPER_RESULTS, KEEPER_MIN_SCORE, KEEPER_DOC_RESULTS, KEEPER_DOC_MIN_SCORE)
    else:
        limits = (MEMORY_RESULTS, MEMORY_MIN_SCORE, DOC_RESULTS, DOC_MIN_SCORE)
    memory_limit, memory_min, doc_limit, doc_min = limits

    memories = best(
        [(score(query_vector, query_words, r["text"], r["embedding"]), r["text"])
         for r in memory_rows],
        memory_limit,
        memory_min,
    )
    documents = best(
        [(score(query_vector, query_words, r["text"], r["embedding"]),
          {"name": r["name"], "text": r["text"]})
         for r in chunk_rows],
        doc_limit,
        doc_min,
    )
    chats = search_chats(question, chat_id) if keeper_mode else []

    return {"memories": memories, "documents": documents, "chats": chats}


def context_prompt(found):
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
