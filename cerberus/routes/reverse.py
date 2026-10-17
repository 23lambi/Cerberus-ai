# The Reverse panel: send a file, get back what Cerberus found in it.
# The real work is in cerberus/reverse.py.

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from cerberus import reverse, settings, signs, tools
from cerberus.config import MAX_UPLOAD_MB, THINK_MAX_TOKENS
from cerberus.ollama import OllamaError, can_think, can_use_tools, trim_history
from cerberus.prompts import REVERSE_FACTS, REVERSE_TOOLS_NOTE
from cerberus.routes.chat import line
from cerberus.schemas import Message

REVERSE_MAX_TOKENS = 1200  # explanations are longer than chat answers
KEEP_FILES = 3

# The last few files, in memory only (never on disk), by their sha256. The
# tools need the file itself (to disassemble any function), but the page
# only sends the facts with a question. A dict keeps the order things
# were added, so the oldest file is the first one.
recent_files = {}

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
    facts = reverse.analyze(name, data)
    recent_files[facts["sha256"]] = data
    while len(recent_files) > KEEP_FILES:
        recent_files.pop(next(iter(recent_files)))  # forget the oldest
    return facts


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
    tools: bool = False


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
    toolbox = tools.REVERSE_TOOLS if req.tools and await can_use_tools(req.model) else []
    if toolbox:
        system += REVERSE_TOOLS_NOTE
    history = [{"role": m.role, "content": m.content} for m in trim_history(req.messages)]
    messages = [{"role": "system", "content": system}] + history

    think = req.think and await can_think(req.model)
    max_tokens = REVERSE_MAX_TOKENS + (THINK_MAX_TOKENS if think else 0)

    # The file itself, for the tools (None if it was dropped long ago).
    tool_context = tools.Context(file=recent_files.get(req.facts.get("sha256")))

    async def generate():
        try:
            events = tools.stream_with_tools(
                req.model, messages, max_tokens, think, toolbox, tool_context
            )
            async for kind, value in events:
                if kind in ("stats", "tool"):
                    yield line(type=kind, **value)
                else:
                    yield line(type=kind, text=value)
        except OllamaError as error:
            yield line(type="error", text=str(error))

    return StreamingResponse(generate(), media_type="application/x-ndjson")
