# Web search (Stage 3, step 3): from a question to a few web sources.
#   0. decide whether the web is needed at all, and what to search for
#   1. search with SearXNG (websearch.py)
#   2. read the best pages, all at the same time (webpage.py)
#   3. keep only the pieces of those pages that fit the question
#
# The model's context window is small, so it never gets whole pages:
# only WEB_PIECES pieces of about 800 characters, grouped per page, so
# that source [1] is always one web page.

import asyncio
import re
from urllib.parse import urlsplit

from cerberus import keeper, webpage, websearch
from cerberus.config import WEB_PAGES, WEB_PIECES, WEB_PIECES_PER_PAGE
from cerberus.ollama import OllamaError, can_think, stream_chat
from cerberus.prompts import WEB_PLAN_PROMPT
from cerberus.websearch import WebError

# ---------- 0. Is the web needed? ----------
#
# The Web pill means "you MAY search", not "always search". Like the Guard
# (guard.py), this tries fast rules first and asks the Helper model only
# when it's on, because a small model decides in about a second.

# Words of small talk. A message made ONLY of these ("hello there",
# "thanks a lot", "γεια σου") never needs the web.
SMALL_TALK = {
    "hi", "hello", "hey", "hiya", "yo", "sup", "good", "morning", "afternoon",
    "evening", "night", "thanks", "thank", "you", "so", "very", "much", "a", "lot",
    "thx", "ty", "ok", "okay", "cool", "nice", "great", "perfect", "awesome",
    "yes", "yeah", "yep", "no", "nope", "sure", "bye", "goodbye", "see", "later",
    "how", "are", "is", "it", "going", "doing", "who", "what", "can", "do", "lol",
    "there", "cerberus", "friend", "again", "buddy", "mate", "all", "i'm", "im",
    "fine", "well", "and", "today", "γεια", "γειά", "σου", "σας", "καλημέρα",
    "καλησπέρα", "καληνύχτα", "ευχαριστώ", "πολύ", "ναι", "όχι", "τι", "κάνεις",
}

# Words that mean "this changes over time": then the web is worth it.
RECENT = re.compile(
    r"\b(latest|newest|recent(ly)?|current(ly)?|today|tonight|yesterday|tomorrow|"
    r"this (week|month|year)|right now|news|prices?|costs?|weather|forecast|scores?|"
    r"released?|release date|versions?|updates?|who won|stocks?|20\d\d)\b|"
    r"σήμερα|ειδήσεις|τιμή|καιρός",
    re.IGNORECASE,
)

# Tasks done from the message itself: writing, translating, fixing code...
# Only used without a Helper, when nobody smarter can decide.
OWN_TASK = re.compile(
    r"^(please\s+)?(write|compose|draft|translate|summari[sz]e|rewrite|rephrase|"
    r"fix|refactor|debug|calculate|solve|convert|format|shorten|explain (this|that|it))\b",
    re.IGNORECASE,
)


# A short "thank you" is small talk, whatever comes after: "thanks, that helped!"
THANKS = re.compile(r"^(thanks|thank you|thx|ty|ευχαριστώ)\b", re.IGNORECASE)

# Plain arithmetic, like "What is 17 * 23?": the model (or the calculate
# tool) can do that, the internet adds nothing.
ARITHMETIC = re.compile(
    r"^\s*(what is|what's|calculate|compute|how much is)?[\s\d.,+\-*/×÷^()%x=]+\??\s*$",
    re.IGNORECASE,
)

# Words that point back at the conversation: "it", "that one", "the first one".
REFERS_BACK = re.compile(
    r"\b(it|its|it's|that|this|they|them|those|these|he|she|his|her|"
    r"the (first|second|third|last|other) one|more detail|you said|above)\b",
    re.IGNORECASE,
)


def is_small_talk(message):
    # "Hello there!" -> {"hello", "there"}: punctuation and emoji are dropped.
    words = re.sub(r"[^\w\s']", " ", message.lower()).split()
    if not 0 < len(words) <= 8:
        return False
    return all(word in SMALL_TALK for word in words) or bool(THANKS.match(message.strip()))


def with_topic(question, recent):
    """A follow-up like "and when was it released?" with the topic in front.

    Without a Helper to rewrite it, the earlier question is the best guess
    of what "it" means: "What's new in Python 3.15? and when was it released?"
    """
    earlier = [m["content"] for m in recent if m["role"] == "user"]
    if earlier and len(question.split()) <= 10 and REFERS_BACK.search(question):
        return earlier[-1][:200] + " " + question
    return question


async def ask_helper(model, question, recent):
    """The Helper's decision: a search query, "" for "no search", or None if it failed."""
    # The last messages go along, so a follow-up like "and when was it
    # released?" becomes a real query like "Python 3.15 release date".
    lines = [
        f"{'User' if m['role'] == 'user' else 'Cerberus'}: {m['content'][:300]}"
        for m in recent
    ]
    content = f"Last message: {question[:1000]}"
    if lines:
        content = "Conversation so far:\n" + "\n".join(lines) + "\n\n" + content
    messages = [
        {"role": "system", "content": WEB_PLAN_PROMPT},
        {"role": "user", "content": content},
    ]
    answer = ""
    try:
        async for piece in stream_chat(model, messages, max_tokens=40, temperature=0):
            answer += piece
    except OllamaError:
        return None
    # Models add quotes, dots and extra lines; keep the first line, cleaned.
    line = answer.strip().splitlines()[0].strip(" \"'`.") if answer.strip() else ""
    if not line:
        return None
    if line.upper().startswith("NONE"):
        return ""
    return line[:200]


async def plan(question, recent=(), helper=None, memory=False):
    """What to search the web for, or None when it isn't needed.

    recent: the messages before this one (for follow-up questions).
    helper: the Helper model, or None. memory: the Guard said "memory".
    """
    # About you or your memories: the answer is here, not on the internet.
    if memory or is_small_talk(question):
        return None
    needs = bool(RECENT.search(question))

    # A thinking model would think for seconds just to say NONE: like the
    # Guard, only a normal Helper is asked.
    if helper and not await can_think(helper):
        decided = await ask_helper(helper, question, recent)
        if decided == "":
            # "latest", "today"... win over a NONE: those always change.
            return with_topic(question, recent) if needs else None
        if decided:
            return decided
        # None: the Helper failed, so the rules below decide.

    if not needs and (OWN_TASK.match(question.strip()) or ARITHMETIC.match(question)):
        return None
    # Not sure: search. A wasted search costs a few seconds; a missing one
    # gives an outdated answer.
    return with_topic(question, recent)


async def read(result):
    """The page of a search result, or its snippet when the page can't be read."""
    try:
        page = await webpage.fetch_page(result["url"])
    except WebError:
        # Blocked, broken or too slow: the short text under the search
        # result is still better than nothing.
        return {"url": result["url"], "title": result["title"], "text": result["snippet"]}
    return {**page, "title": page["title"] or result["title"]}


def by_words(question_words, pieces):
    """Round 1: the positions of the pieces sharing the most words with the question."""
    # Sorted by score (highest first), then position: when nothing matches,
    # the start of a page wins, which is usually where the point is made.
    ranked = sorted(
        range(len(pieces)),
        key=lambda i: (-keeper.score(None, question_words, pieces[i], None), i),
    )
    return ranked[:WEB_PIECES_PER_PAGE]


async def pick(question, pages):
    """The best pieces of all pages, as (page number, position, text)."""
    question_words = keeper.words(question)
    candidates = []
    for page_number, page in enumerate(pages):
        pieces = keeper.split_text(page["text"])
        candidates += [(page_number, i, pieces[i]) for i in by_words(question_words, pieces)]
    if not candidates:
        return []

    # Round 2, by meaning: only for these few pieces, so it stays fast.
    question_vector = await keeper.embed_one(question, "query")
    vectors = await keeper.embed_texts([text for _, _, text in candidates], "document")
    if question_vector and all(vectors):
        scores = [keeper.cosine(question_vector, vector) for vector in vectors]
    else:
        # No embedding model: the word scores decide.
        scores = [keeper.score(None, question_words, text, None) for _, _, text in candidates]

    # Best score first; on a tie, the better search result, then the earlier piece.
    order = sorted(
        range(len(candidates)),
        key=lambda k: (-scores[k], candidates[k][0], candidates[k][1]),
    )
    return [candidates[k] for k in order[:WEB_PIECES]]


async def research(base_url, question):
    """Web sources for a question: [{"name", "url", "text", "kind": "web"}, ...].

    Raises WebError when the search itself fails (SearXNG not running...).
    """
    results = await websearch.search(base_url, question)
    # gather runs the downloads at the same time: 3 pages take as long as the slowest.
    pages = await asyncio.gather(*(read(result) for result in results[:WEB_PAGES]))
    chosen = await pick(question, pages)

    # One source per page, its pieces in the order they appear on the page.
    by_page = {}
    for page_number, position, text in chosen:
        by_page.setdefault(page_number, []).append((position, text))

    sources = []
    for page_number in sorted(by_page):  # better search results first
        page = pages[page_number]
        host = urlsplit(page["url"]).hostname or page["url"]
        pieces = [text for _, text in sorted(by_page[page_number])]
        sources.append({
            # "Title (site)", so you can see where it comes from at a glance.
            "name": f"{page['title']} ({host})" if page["title"] else host,
            "url": page["url"],
            "text": "\n[...]\n".join(pieces),  # [...] = something left out here
            "kind": "web",
            # What was searched for, saved with the answer, so you can see
            # it again when you reopen the chat.
            "query": question,
        })
    return sources
