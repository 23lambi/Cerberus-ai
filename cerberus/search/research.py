# The research agent (Stage 4): a big question becomes a sourced report.
#
#   1. PLAN    the model splits the question into a few web searches
#   2. SEARCH  each one with SearXNG, keeping the best new pages
#   3. READ    all pages at the same time, and keep the best pieces per search
#   4. WRITE   a report with [1] citations, saved as a Markdown document
#
# An agent is a model working in steps toward a goal. Here the CODE decides
# the steps and the model only fills in two of them (the plan and the
# report). It gets no tools that could change anything, so a web page with
# hidden instructions has nothing to trick it into.
#
# Everything is bounded, because the model's context window is small and
# a CPU reads only about 100 tokens a second: at most RESEARCH_QUERIES
# searches, RESEARCH_PAGES_PER_QUERY pages each, RESEARCH_PIECES_PER_QUERY
# pieces each. A report takes a few minutes on a CPU.

import asyncio
import re
from contextlib import aclosing

from cerberus.storage import database, keeper
from cerberus.engines import ollama
from cerberus.core import model_settings
from cerberus.search import web, websearch
from cerberus.chat.budget import ContextTooLarge, fit
from cerberus.core.config import (
    RESEARCH_MAX_TOKENS,
    RESEARCH_PAGES_PER_QUERY,
    RESEARCH_PIECES_PER_QUERY,
    RESEARCH_QUERIES,
    THINK_MAX_TOKENS,
)
from cerberus.engines.ollama import OllamaError, can_think, stream_chat
from cerberus.chat.prompts import RESEARCH_PLAN, RESEARCH_WRITE
from cerberus.search.websearch import WebError


def progress(text, **extra):
    # A step the page shows while the agent works ("Reading 6 pages...").
    return {"type": "progress", "text": text, **extra}


# ---------- 1. Plan ----------


def parse_plan(answer, question, known):
    """The searches in the model's plan: one per line, cleaned, at most RESEARCH_QUERIES."""
    queries = []
    for line in answer.splitlines():
        # Models like to number or bullet their lines: "1. ...", "- ...".
        query = re.sub(r"^\s*(\d+[.)]|[-*•])\s*", "", line).strip(" \"'`.")
        if not query or query.endswith(":") or len(query) > 120:
            continue  # empty, a heading like "Searches:", or a whole paragraph
        if query.lower() in (q.lower() for q in queries):
            continue
        # Like web.ask_helper: a number found nowhere in the conversation
        # was guessed, and a guessed answer makes a bad search.
        if any(number not in known for number in re.findall(r"\d+", query)):
            continue
        queries.append(query)
    # A plan the model got wrong: then just search the question itself.
    return queries[:RESEARCH_QUERIES] or [question]


async def plan(model, question, known):
    messages = [
        {"role": "system", "content": RESEARCH_PLAN},
        {"role": "user", "content": question},
    ]
    answer = ""
    async for piece in stream_chat(model, messages, max_tokens=120, temperature=0.2):
        answer += piece
    return parse_plan(answer, question, known)


# ---------- 4. Saving the report ----------


def report_name(question):
    # "Compare local LLM runtimes?" -> research-compare-local-llm-runtimes.md
    # \w keeps letters of every language, so Greek questions work too.
    slug = re.sub(r"\W+", "-", question.lower()).strip("-")[:40].strip("-")
    return f"research-{slug or 'report'}.md"


def with_title(report, question):
    """The report with the question as its heading, so the document has a
    title (the Docs list shows it). A report that has one already keeps it."""
    if report.lstrip().startswith("#"):
        return report
    title = " ".join(question.split())[:200]  # one line, never a whole essay
    return f"# {title}\n\n{report.lstrip()}"


def with_references(report, sources):
    """The report with a Sources list of real links at the end, for the document."""
    lines = []
    for source in sources:
        if source["kind"] == "web":
            # Brackets in a title would break the Markdown link.
            name = source["name"].replace("[", "(").replace("]", ")")
            lines.append(f"{source['number']}. [{name}]({source['url']})")
    if not lines:
        return report
    return report.rstrip() + "\n\n## Sources\n\n" + "\n".join(lines) + "\n"


async def save_report(name, content, project_id):
    """Save as an editable Markdown document, searchable like any other."""
    pieces = keeper.split_text(content)
    vectors = await keeper.embed_texts(pieces, "document")
    chunks = [(i, text, keeper.to_json(vector)) for i, (text, vector) in enumerate(zip(pieces, vectors))]
    return database.write_document(name, content, project_id, chunks)


# ---------- All steps ----------


async def run(ctx, model, chat_id=None):
    """The agent, as a stream of events for turns.respond (like a chat answer)."""
    # Everything the user said, for the "no guessed numbers" check.
    known = " ".join(m["content"] for m in ctx.history)

    # 1. Plan
    yield progress("Planning the research…")
    queries = await plan(model, ctx.question, known)
    yield progress("Plan: " + " · ".join(f'"{q}"' for q in queries), queries=queries)

    # 2. Search. One search after the other: SearXNG asks several engines
    # each time, and many at once would get us blocked (CAPTCHA).
    used = set()  # a page found by two searches is read only once
    found = []  # (query, the new results for it)
    failure = None
    for query in queries:
        yield progress(f'Searching for "{query}"…')
        try:
            results = await websearch.search(query)
        except WebError as error:
            failure = str(error)
            continue
        fresh = [r for r in results if r["url"] not in used][:RESEARCH_PAGES_PER_QUERY]
        used.update(r["url"] for r in fresh)
        found.append((query, fresh))
    total = sum(len(results) for _, results in found)
    if not total:
        raise OllamaError("The research found no web pages" + (f": {failure}" if failure else "."))

    # 3. Read all pages at the same time, then keep the best pieces per
    # search, so every part of the question gets its own evidence.
    yield progress(f"Reading {total} pages…")
    pages_per_query = await asyncio.gather(*(
        asyncio.gather(*(web.read(result) for result in results)) for _, results in found
    ))
    yield progress("Choosing the best parts…")
    for (query, _), pages in zip(found, pages_per_query):
        pages = list(pages)
        chosen = await web.pick(query, pages, RESEARCH_PIECES_PER_QUERY)
        for source in web.as_sources(pages, chosen, query):
            ctx.sources.append({**source, "number": len(ctx.sources) + 1})

    # 4. Write. A thinking model thinks first (like stream_chat), so it
    # gets room for that too.
    think = await can_think(model)
    max_tokens = RESEARCH_MAX_TOKENS + (THINK_MAX_TOKENS if think else 0)
    messages = ctx.messages(extra=RESEARCH_WRITE)
    while True:
        try:
            fit(messages, max_tokens, num_ctx=model_settings.num_ctx(model))
            break
        except ContextTooLarge:
            # Too much to read: drop web sources from the end, like context.py.
            if not ctx.web_pages():
                raise OllamaError("This question and its context are too large for a research report.") from None
            ctx.sources.pop()
            messages = ctx.messages(extra=RESEARCH_WRITE)

    # The sources are saved with the answer (turns.py reads ctx.sources).
    yield {"type": "sources", "sources": ctx.sources}
    yield progress(f"Writing the report from {ctx.web_pages()} sources…")
    report = ""
    # ollama.stream_events, looked up in the module each time (not imported
    # by name), so a replacement there (like the tests' fake) is used too.
    async with aclosing(ollama.stream_events(model, messages, max_tokens, think=think)) as events:
        async for kind, value in events:
            if kind == "content":
                report += value
                yield {"type": "content", "text": value}
            elif kind == "thinking":
                yield {"type": "thinking", "text": value}
            elif kind == "stats":
                yield {"type": "stats", **value}

    if not report.strip():
        return
    # Only a finished report becomes a document; Stop keeps the partial one
    # in the chat (turns.py), but doesn't save half a report as a file.
    chat = database.get_chat_info(chat_id) if chat_id else None
    name = report_name(ctx.question)
    try:
        content = with_title(with_references(report, ctx.sources), ctx.question)
        doc = await save_report(name, content, chat and chat["project_id"])
    except ValueError:  # the project was deleted meanwhile
        yield progress("The report could not be saved as a document: its project no longer exists.")
        return
    yield progress(f"Report saved as {name}", document_id=doc["id"])
