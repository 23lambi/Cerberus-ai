"""One lifecycle for chat and Deep think: prepare, stream, stop, commit.

Run Cerberus with one server worker. The active runs belong to that process;
SQLite still checks the history again inside the save transaction.
"""

import asyncio
import json
from contextlib import suppress

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from cerberus import context, database
from cerberus.ollama import OllamaError

active = {}  # chat id -> stop event; never contains finished runs


def require_idle(chat_id):
    if chat_id in active:
        raise HTTPException(409, "This chat is still answering. Stop it before changing it.")


async def until_stopped(awaitable, stop):
    """Cancel an in-flight Ollama read (or context preparation) on Stop."""
    work = asyncio.ensure_future(awaitable)
    stopping = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait((work, stopping), return_when=asyncio.FIRST_COMPLETED)
        # Prefer a completed chunk: it may be the final piece already received.
        if work in done:
            return await work
        raise InterruptedError
    finally:
        for task in (work, stopping):
            if not task.done():
                task.cancel()
        await asyncio.gather(work, stopping, return_exceptions=True)


async def respond(req, produce):
    stop = asyncio.Event()
    expected_count = 0
    if req.chat_id:
        require_idle(req.chat_id)
        chat = database.get_chat(req.chat_id)
        if chat is None:
            raise HTTPException(404, "Chat not found")
        expected_count = len(chat["messages"])
        previous = [m.model_dump() for m in req.messages[:-1]]
        if previous != chat["messages"]:
            raise HTTPException(409, "This chat changed. Reopen it before sending another message.")
        active[req.chat_id] = stop

    ctx = None
    try:
        ctx = await until_stopped(context.prepare(req), stop)
    except InterruptedError:
        pass
    except BaseException:
        if req.chat_id:
            active.pop(req.chat_id, None)
        raise

    async def generate():
        reply = ""
        saved = False
        error = None
        source = None
        try:
            if ctx is not None and not stop.is_set():
                if ctx.sources:
                    yield json.dumps({"type": "sources", "step": "sources", "sources": ctx.sources}) + "\n"
                source = produce(ctx)
                while not stop.is_set():
                    try:
                        item = await until_stopped(anext(source), stop)
                    except (StopAsyncIteration, InterruptedError):
                        break
                    if item.get("type") == "content" or item.get("step") == "final":
                        reply += item["text"]
                    yield json.dumps(item) + "\n"
        except OllamaError as failure:
            error = str(failure)
            yield json.dumps({"type": "error", "step": "error", "text": error}) + "\n"
        finally:
            # No await between the two INSERTs: cancellation cannot split a turn.
            # This also runs on browser disconnect, keeping any partial answer.
            try:
                if req.chat_id and reply:
                    saved = database.save_turn(
                        req.chat_id, ctx.question, reply, ctx.images, ctx.seen, expected_count, sources=ctx.sources
                    )
                    if not saved:
                        error = "The chat changed while answering. This answer was not saved; reopen the chat."
            finally:
                if req.chat_id:
                    active.pop(req.chat_id, None)
                if source is not None:
                    with suppress(Exception):
                        await source.aclose()
        # Sent AFTER the database commit. Stop keeps reading until this arrives.
        yield json.dumps({"type": "done", "step": "done", "saved": saved,
                          "stopped": stop.is_set(), "error": error}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson",
                             headers=ctx.headers() if ctx else {})
