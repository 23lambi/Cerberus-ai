# The Models panel: the installed models, searching ollama.com, and
# downloading or deleting models. The work is in ollama.py and library.py.

import asyncio
import json
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from cerberus import huggingface, library, ollama, openai_api

router = APIRouter(prefix="/models")


@router.get("/local")
async def local_models():
    """Discover running local apps at known addresses, not arbitrary ports."""
    candidates = [{"preset": preset, "name": openai_api.PRESETS[preset]["name"],
                   "url": openai_api.PRESETS[preset]["url"], "key": ""}
                  for preset in ("lmstudio", "jan", "llamacpp")]
    if ollama.engine() == "openai":
        chosen = openai_api.current()
        if chosen["url"] and not chosen["cloud"]:
            # A custom port or authenticated local server already configured by the user.
            candidates = [item for item in candidates if item["url"] != chosen["url"]]
            candidates.insert(0, chosen)

    async def probe(candidate):
        try:
            names = await openai_api.list_models(candidate, timeout=2)
        except openai_api.EngineError:
            return None
        return {"preset": candidate["preset"], "name": candidate["name"],
                "url": candidate["url"], "models": names}

    found = await asyncio.gather(*(probe(candidate) for candidate in candidates))
    return {"engines": [item for item in found if item is not None]}

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


@router.get("/huggingface")
async def search_huggingface(q: str = "", order: str = "popular", category: str = "chat"):
    """Search Hugging Face for GGUF models (the ones Ollama can run), or
    without words, browse one category: chat, vision or embedding."""
    try:
        if q.strip():
            return {"models": await huggingface.search(q.strip()[:100])}
        return {"models": await huggingface.browse(order, category)}
    except huggingface.HuggingFaceError as error:
        raise HTTPException(502, str(error)) from None


@router.get("/huggingface/versions")
async def huggingface_versions(repo: str):
    """The versions of one Hugging Face model (Q4_K_M, Q8_0...) with their sizes."""
    try:
        return await huggingface.versions(repo.strip())
    except huggingface.HuggingFaceError as error:
        status = 422 if "isn't a Hugging Face" in str(error) else 404 if "doesn't exist" in str(error) else 502
        raise HTTPException(status, str(error)) from None


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
