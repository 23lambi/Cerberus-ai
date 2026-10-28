# The Models panel: the installed models, searching ollama.com, and
# downloading or deleting models. The work is in ollama.py and library.py.

import json
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from cerberus import library, ollama

router = APIRouter(prefix="/models")

# A model name: "llama3.2:3b", "nomic-embed-text", "hf.co/user/model:Q4_K_M".
NAME = re.compile(r"[A-Za-z0-9][\w.\-/:]{0,199}")


def check_name(name):
    name = name.strip()
    if not NAME.fullmatch(name):
        raise HTTPException(422, "That isn't a valid model name, like llama3.2:3b.")
    return name


@router.get("/installed")
async def installed():
    """Every installed model: its details, what it can do, and whether it's in memory."""
    try:
        models = await ollama.installed()
    except ollama.OllamaError as error:
        raise HTTPException(503, str(error)) from None
    in_memory = await ollama.running()
    for model in models:
        model["capabilities"] = await ollama.capabilities(model["name"])
        model["in_memory"] = in_memory.get(model["name"])  # bytes, or None
    return {"models": models}


@router.get("/library")
async def search_library(q: str = "", order: str = "popular"):
    """Search the Ollama library, or without words, browse it."""
    try:
        if q.strip():
            return {"models": await library.search(q.strip()[:100])}
        return {"models": await library.browse("newest" if order == "newest" else "popular")}
    except library.LibraryError as error:
        raise HTTPException(502, str(error)) from None


class PullIn(BaseModel):
    model: str


@router.post("/pull")
async def pull(body: PullIn):
    """Download a model. The steps stream as NDJSON, like a chat answer:
    {"type": "progress", "status": ..., "completed": ..., "total": ...},
    then {"type": "done"} or {"type": "error", "text": ...}.
    Closing the connection (Cancel in the page) stops the download.
    """
    name = check_name(body.model)

    async def generate():
        try:
            async for step in ollama.pull(name):
                yield json.dumps({
                    "type": "progress",
                    "status": step.get("status", ""),
                    "completed": step.get("completed"),
                    "total": step.get("total"),
                }) + "\n"
            yield json.dumps({"type": "done", "model": name}) + "\n"
        except ollama.OllamaError as error:
            yield json.dumps({"type": "error", "text": str(error)}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


# The name goes in the query (?name=...), because names contain "/" and ":".
@router.delete("/installed")
async def delete(name: str):
    name = check_name(name)
    try:
        await ollama.delete(name)
    except ollama.OllamaError as error:
        raise HTTPException(404 if "not found" in str(error) else 502, str(error)) from None
    return {"deleted": name}
