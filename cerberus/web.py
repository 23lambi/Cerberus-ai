# Web search (Stage 3, step 3): from a question to a few web sources.
#   1. search with SearXNG (websearch.py)
#   2. read the best pages, all at the same time (webpage.py)
#   3. keep only the pieces of those pages that fit the question
#
# The model's context window is small, so it never gets whole pages:
# only WEB_PIECES pieces of about 800 characters, grouped per page, so
# that source [1] is always one web page.

import asyncio
from urllib.parse import urlsplit

from cerberus import keeper, webpage, websearch
from cerberus.config import WEB_PAGES, WEB_PIECES, WEB_PIECES_PER_PAGE
from cerberus.websearch import WebError


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
        })
    return sources
