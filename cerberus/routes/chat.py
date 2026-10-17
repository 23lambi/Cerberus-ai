# POST /chat: the heart of Cerberus. One message comes in, context.py
# builds the system prompt (personality, project notes, memories, summary),
# and the answer is streamed back to the browser piece by piece.
#
# The stream is NDJSON: one JSON object per line, each with a "type":
#   {"type": "thinking", "text": "..."}   the model's reasoning (Think on)
#   {"type": "content", "text": "..."}    a piece of the answer
#   {"type": "stats", "tokens": 312, ...} once, at the end
#   {"type": "error", "text": "..."}      when Ollama fails
# Plain text could only carry the answer; JSON lines can carry all four.

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from cerberus import context, database, recap, settings
from cerberus.config import DEFAULT_MAX_TOKENS, THINK_MAX_TOKENS
from cerberus.ollama import OllamaError, can_think, stream_chat, stream_events
from cerberus.schemas import ChatRequest

# A router is a group of URLs that main.py plugs into the app.
router = APIRouter()


def line(**fields):
    # line(type="content", text="Hi") -> '{"type": "content", "text": "Hi"}\n'
    # **fields collects all keyword arguments into one dict.
    return json.dumps(fields) + "\n"


@router.post("/chat")
async def chat(req: ChatRequest):
    ctx = await context.prepare(req)
    question = ctx.question
    messages = ctx.messages()

    # Only think when the user asked for it AND the model can do it.
    # Thinking uses tokens too, so it gets its own budget on top.
    think = req.think and await can_think(req.model)
    max_tokens = DEFAULT_MAX_TOKENS + (THINK_MAX_TOKENS if think else 0)

    # A generator: StreamingResponse sends each piece it yields to the
    # browser right away, so the user sees the answer being written.
    async def generate():
        reply = ""
        failed = False
        if ctx.seen:
            # First, what the Eyes saw, so the page can show it and keep it.
            yield line(type="seen", text=ctx.seen, model=ctx.eyes)
        try:
            async for kind, value in stream_events(req.model, messages, max_tokens, think=think):
                if kind == "stats":
                    # **value spreads the stats dict into the line's fields.
                    yield line(type="stats", **value)
                    continue
                if kind == "content":
                    reply += value  # only the answer is saved, not the thinking
                yield line(type=kind, text=value)
        except OllamaError as error:
            failed = True
            yield line(type="error", text=str(error))
        finally:
            # Runs at the end, and also when the user presses Stop.
            # Question and answer are saved together, so a chat never has
            # a question without its answer.
            if req.chat_id and reply and not failed:
                database.save_message(req.chat_id, "user", question, ctx.images, ctx.seen)
                database.save_message(req.chat_id, "assistant", reply)

    return StreamingResponse(
        generate(), media_type="application/x-ndjson", headers=ctx.headers()
    )


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
