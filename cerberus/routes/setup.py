# The Setup window (static/setup.js): checks, getting Ollama, and SearXNG.

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from cerberus import engine, ollama, openai_api, settings, setup

router = APIRouter(prefix="/setup")


@router.get("/status")
async def status():
    return await setup.status()


@router.post("/ollama/download")
async def download_ollama():
    """Download and unpack Ollama, then start it. The steps stream as NDJSON,
    like a model download; closing the connection (Cancel) stops it."""

    async def generate():
        try:
            async for step in engine.download():
                yield json.dumps(step) + "\n"
            yield json.dumps({"step": "starting"}) + "\n"
            await engine.start()
            yield json.dumps({"step": "running"}) + "\n"
        except engine.EngineError as error:
            yield json.dumps({"step": "error", "text": str(error)}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@router.post("/ollama/start")
async def start_ollama():
    try:
        await engine.start()
    except engine.EngineError as error:
        raise HTTPException(409, str(error)) from None
    return {"running": True}


@router.post("/searxng/prepare")
def prepare_searxng():
    return setup.prepare_searxng()


# ---------- Choosing the AI engine ----------


@router.get("/engines")
def engines():
    """The engines to choose from, and the current choice (never the key)."""
    chosen = openai_api.current()
    return {
        "engine": ollama.engine(),
        "presets": openai_api.PRESETS,
        "openai": {"preset": chosen["preset"], "url": chosen["url"], "cloud": chosen["cloud"],
                   "key_set": bool(chosen["key"])},
    }


class EngineIn(BaseModel):
    engine: str = Field(pattern="^(ollama|openai)$")
    preset: str = "custom"
    url: str = Field(default="", max_length=300)
    key: str = Field(default="", max_length=500)  # "" = keep the key you have


@router.post("/engine")
async def choose_engine(body: EngineIn):
    """Save the engine choice, then test it by asking for its models."""
    if body.engine == "openai":
        if body.preset not in openai_api.PRESETS:
            raise HTTPException(422, "Unknown engine.")
        url = body.url.strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(422, "The address must start with http:// or https://.")
        # The preset's own address is saved as "" so it follows the preset.
        if url == openai_api.PRESETS[body.preset]["url"]:
            url = ""
        settings.update({"engine": "openai", "openai_preset": body.preset, "openai_url": url, "openai_key": body.key})
    else:
        settings.update({"engine": "ollama"})
    ollama.capabilities_cache.clear()  # another engine: other models
    try:
        models = await ollama.list_models()
    except ollama.OllamaError as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True, "models": len(models)}
