from contextlib import aclosing

# POST /chat: the heart of Cerberus. One message comes in, context.py
# builds the system prompt (personality, project notes, memories, summary),
# and the answer is streamed back to the browser piece by piece.
#
# The stream is NDJSON: one JSON object per line, each with a "type":
#   {"type": "thinking", "text": "..."}   the model's reasoning (Think on)
#   {"type": "content", "text": "..."}    a piece of the answer
#   {"type": "tool", "name": ..., "arguments": ..., "result": ...}
#                                         a tool the model used
#   {"type": "stats", "tokens": 312, ...} once, at the end
#   {"type": "error", "text": "..."}      when Ollama fails
# A final done event confirms that saving has finished.

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cerberus import database, recap, settings, tools, turns
from cerberus.config import DEFAULT_MAX_TOKENS, THINK_MAX_TOKENS
from cerberus.ollama import OllamaError, can_think, can_use_tools, stream_chat
from cerberus.prompts import TOOLS_NOTE
from cerberus.schemas import ChatRequest

# A router is a group of URLs that main.py plugs into the app.
router = APIRouter()


def line(**fields):
    # line(type="content", text="Hi") -> '{"type": "content", "text": "Hi"}\n'
    # **fields collects all keyword arguments into one dict.
    return json.dumps(fields) + "\n"


@router.post("/chat")
async def chat(req: ChatRequest):
    async def produce(ctx):
        toolbox = tools.CHAT_TOOLS if req.tools and await can_use_tools(req.model) else []
        messages = ctx.messages(extra=TOOLS_NOTE if toolbox else "")
        think = req.think and await can_think(req.model)
        max_tokens = DEFAULT_MAX_TOKENS + (THINK_MAX_TOKENS if think else 0)
        if ctx.seen:
            yield {"type": "seen", "text": ctx.seen, "model": ctx.eyes}
        async with aclosing(tools.stream_with_tools(
            req.model, messages, max_tokens, think, toolbox, tools.Context(chat_id=req.chat_id)
        )) as events:
            async for kind, value in events:
                yield {"type": kind, **value} if kind in ("stats", "tool") else {"type": kind, "text": value}

    return await turns.respond(req, produce)


class TitleRequest(BaseModel):
    model: str


@router.post("/chats/{chat_id}/title")
async def make_title(chat_id: int, req: TitleRequest):
    # The page calls this after the first answer of a new chat.
    chat = database.get_chat(chat_id)
    if chat is None or len(chat["messages"]) < 2:
        raise HTTPException(status_code=404, detail="Nothing to title yet")

    question = chat["messages"][0]["content"]
    answer = chat["messages"][1]["content"][:500]
    prompt = (
        "Write a short title, at most 5 words, for a chat that starts like this. "
        "Reply with only the title, no quotes.\n\n"
        f"User: {question}\nAssistant: {answer}"
    )

    # A title is a background job, so the helper model writes it.
    helper = await settings.jobs_model(req.model)
    title = ""
    try:
        async for piece in stream_chat(helper, [{"role": "user", "content": prompt}]):
            title += piece
    except OllamaError:
        return {"title": chat["title"]}  # keep the placeholder

    # Clean up what models like to add: keep the first line only, drop
    # quotes and a final dot, and cut at 60 characters.
    title = title.strip().splitlines()[0].strip(' "\'.')[:60] if title.strip() else ""
    if title:
        database.set_chat_title(chat_id, title)
    return {"title": title or chat["title"]}


class RecapRequest(BaseModel):
    model: str


@router.post("/chats/{chat_id}/recap")
async def recap_chat(chat_id: int, req: RecapRequest):
    # The page calls this when you leave a project chat.
    # The recap is null when there was nothing new to write.
    # Recaps are background jobs, so the helper model writes them.
    helper = await settings.jobs_model(req.model)
    return {"recap": await recap.make_recap(chat_id, helper)}
