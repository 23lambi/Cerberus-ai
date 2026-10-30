# The Setup window (static/setup.js): checks, getting Ollama, and SearXNG.

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from cerberus.engines import engine, llamacpp, ollama, openai_api
from cerberus.chat.prompts import SETUP_HELLO
from cerberus.core import settings, setup
from cerberus.search import searxng, websearch
from cerberus.core.config import WEB_ENGINES

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


class HelloRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)


@router.post("/hello")
async def hello(req: HelloRequest):
    """The last setup step: a first short answer from the chosen model, so you
    see that everything works. It streams as NDJSON; nothing is saved."""
    messages = [{"role": "system", "content": settings.brain()},
                {"role": "user", "content": SETUP_HELLO}]

    async def generate():
        try:
            async for piece in ollama.stream_chat(req.model, messages, max_tokens=120):
                yield json.dumps({"text": piece}) + "\n"
        except ollama.OllamaError as error:
            yield json.dumps({"error": str(error)}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@router.post("/ollama/start")
async def start_ollama():
    try:
        await engine.start()
    except engine.EngineError as error:
        raise HTTPException(409, str(error)) from None
    return {"running": True}


@router.post("/web/test")
async def test_web_search():
    """One real search with the saved engine, so you see that it works."""
    try:
        found = await websearch.search("Cerberus three-headed dog", limit=3)
    except websearch.WebError as error:
        return {"ok": False, "error": str(error)}
    if not found:
        return {"ok": False, "error": WEB_ENGINES[settings.get("web_engine")] + " answered, but found nothing."}
    return {"ok": True, "count": len(found), "first": found[0]["title"]}


@router.post("/searxng/install")
async def install_searxng():
    """Install SearXNG with Python (searxng.py), choose it, and start it.
    The steps stream as NDJSON, like the Ollama download; Cancel stops it."""

    async def generate():
        try:
            async for step in searxng.install():
                yield json.dumps(step) + "\n"
            settings.update({"web_engine": "searxng", "web_url": searxng.URL})
            yield json.dumps({"step": "starting"}) + "\n"
            await searxng.start()
            yield json.dumps({"step": "running"}) + "\n"
        except searxng.SearxngError as error:
            yield json.dumps({"step": "error", "text": str(error)}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@router.post("/searxng/start")
async def start_searxng():
    # Starting Cerberus's SearXNG chooses it too, at its own address.
    settings.update({"web_engine": "searxng", "web_url": searxng.URL})
    try:
        await searxng.start()
    except searxng.SearxngError as error:
        raise HTTPException(409, str(error)) from None
    return {"running": True}


class SwitchIn(BaseModel):
    on: bool


@router.post("/searxng/switch")
async def switch_searxng(body: SwitchIn):
    """SearXNG's on/off switch. "command": what to run yourself, when
    Cerberus can't switch a Docker SearXNG (Docker needs sudo there)."""
    try:
        command = await searxng.switch(body.on)
    except searxng.SearxngError as error:
        raise HTTPException(409, str(error)) from None
    return {"on": body.on, "command": command}


@router.post("/searxng/remove")
async def remove_searxng():
    # In a thread: deleting thousands of files takes a moment.
    await asyncio.to_thread(searxng.remove)
    return {"removed": True}


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
        "llamacpp": llamacpp.configuration(),
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
        if body.preset == "llamacpp":
            actual_url = url or openai_api.PRESETS["llamacpp"]["url"]
            if actual_url != f"http://127.0.0.1:{settings.get('llamacpp_port')}/v1":
                settings.update({"llamacpp_on": "no"})
        settings.update({"engine": "openai", "openai_preset": body.preset, "openai_url": url, "openai_key": body.key})
    else:
        settings.update({"engine": "ollama"})
    ollama.model_facts_cache.clear()  # another engine: other models
    try:
        models = await ollama.list_models()
    except ollama.OllamaError as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True, "models": len(models)}


class LlamaCppIn(BaseModel):
    binary: str = Field(default="llama-server", min_length=1, max_length=1000)
    model: str = Field(min_length=1, max_length=4000)
    port: int = Field(default=8080, ge=1, le=65535)


@router.post("/llamacpp/start")
async def start_llamacpp(body: LlamaCppIn):
    try:
        await llamacpp.start(body.binary, body.model, body.port)
    except llamacpp.EngineError as error:
        raise HTTPException(409, str(error)) from None
    settings.update({"llamacpp_binary": body.binary, "llamacpp_model": body.model,
                     "llamacpp_port": str(body.port), "llamacpp_on": "yes", "engine": "openai",
                     "openai_preset": "llamacpp", "openai_url": f"http://127.0.0.1:{body.port}/v1"})
    ollama.model_facts_cache.clear()
    return {"running": True}


@router.post("/llamacpp/stop")
async def stop_llamacpp():
    async with llamacpp.lock:
        settings.update({"llamacpp_on": "no"})
        await asyncio.to_thread(llamacpp.stop)
    return {"running": False}
