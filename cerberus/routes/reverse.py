# The Reverse panel: send a file, get back what Cerberus found in it.
# The real work is in cerberus/reverse.py.

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from cerberus import reverse, settings, signs
from cerberus.config import MAX_UPLOAD_MB, THINK_MAX_TOKENS
from cerberus.ollama import OllamaError, can_think, stream_events, trim_history
from cerberus.prompts import REVERSE_FACTS
from cerberus.routes.chat import line
from cerberus.schemas import Message

REVERSE_MAX_TOKENS = 1200  # explanations are longer than chat answers

router = APIRouter(prefix="/reverse")


# Like documents: the file is the request body, its name is in the URL.
# The file is only read in memory; it's never saved and never run.
@router.post("")
async def analyze(request: Request, name: str):
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="The file is empty.")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Files can be up to {MAX_UPLOAD_MB} MB.")
    return reverse.analyze(name, data)


# A second look with ClamAV, a real virus scanner, if it's installed. Its
# own button, because ClamAV needs some seconds to load its pattern list.
@router.post("/clamav")
async def clamav(request: Request):
    data = await request.body()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Files can be up to {MAX_UPLOAD_MB} MB.")
    return await signs.clamav_scan(data)


class ReverseChat(BaseModel):
    model: str
    facts: dict  # what POST /reverse answered; the page sends it back
    messages: list[Message]  # the questions and answers about this file
    think: bool = False


# Ask the model about the file. The file itself is gone (it was never
# saved), so the page sends its facts back with every question. The answer
# streams as NDJSON, exactly like /chat, so the page can reuse its code.
@router.post("/chat")
async def chat(req: ReverseChat):
    # The same brain, plus its reverse-engineering skill, plus the facts.
    # All of it goes in the system prompt: it stays the same for every
    # question about this file, so Ollama's prompt cache can be reused.
    sheet = reverse.fact_sheet(req.facts)
    system = settings.brain("reverse") + REVERSE_FACTS.format(name=req.facts["name"], sheet=sheet)
    history = [{"role": m.role, "content": m.content} for m in trim_history(req.messages)]
    messages = [{"role": "system", "content": system}] + history

    think = req.think and await can_think(req.model)
    max_tokens = REVERSE_MAX_TOKENS + (THINK_MAX_TOKENS if think else 0)

    async def generate():
        try:
            async for kind, value in stream_events(req.model, messages, max_tokens, think=think):
                if kind == "stats":
                    yield line(type="stats", **value)
                else:
                    yield line(type=kind, text=value)
        except OllamaError as error:
            yield line(type="error", text=str(error))

    return StreamingResponse(generate(), media_type="application/x-ndjson")
