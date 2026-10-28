# The page itself, plus small info URLs.

import hashlib
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from cerberus.core import settings
from cerberus.core.version import VERSION
from cerberus.core.config import DATA_DIR, EMBED_MODEL, STATIC_DIR
from cerberus.engines.ollama import (
    OllamaError,
    can_chat,
    can_see,
    can_think,
    can_use_tools,
    list_models,
)
from cerberus.engines import openai_api
from cerberus.engines.ollama import engine, full_name, loaded_models, unload

router = APIRouter()


@router.get("/")
def home():
    # Opening http://127.0.0.1:8000/ sends the whole app: one HTML page.
    # The page then loads its CSS and JS from /static.
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    def versioned_asset(match):
        # New code gets a new URL, including in the desktop webview's cache.
        digest = hashlib.sha256((STATIC_DIR / match[2]).read_bytes()).hexdigest()[:12]
        return f'{match[1]}?v={digest}"'

    html = re.sub(r'((?:src|href)="/static/([^"?]+\.(?:js|css)))"', versioned_asset, html)
    return HTMLResponse(html)


@router.get("/about")
def about():
    # data_dir: where your chats and files are, shown in Settings.
    return {"name": "Cerberus", "version": VERSION, "data_dir": str(DATA_DIR)}


@router.get("/models")
async def models():
    # The models for the dropdown. 503 = "service unavailable": Ollama is down.
    # "thinking" lists the models that can reason, so the page knows when
    # to show the Think checkbox.
    try:
        # Only models that can chat; embedding models are left out.
        names = [name for name in await list_models() if await can_chat(name)]
        thinking = [name for name in names if await can_think(name)]
        vision = [name for name in names if await can_see(name)]
        with_tools = [name for name in names if await can_use_tools(name)]
        # Which engine answers, so the page can say when it's a cloud one.
        if engine() == "openai":
            chosen = openai_api.current()
            about = {"kind": "openai", "name": chosen["name"], "cloud": chosen["cloud"]}
        else:
            about = {"kind": "ollama", "name": "Ollama", "cloud": False}
        return {"models": names, "thinking": thinking, "vision": vision, "tools": with_tools, "engine": about}
    except OllamaError as error:
        raise HTTPException(status_code=503, detail=str(error)) from None


class KeepRequest(BaseModel):
    model: str = ""  # "" = None in the dropdown: keep no model at all


@router.post("/models/keep")
async def keep_only(req: KeepRequest):
    # The page calls this when you pick another model. Every model in RAM
    # is unloaded, except the ones Cerberus still needs:
    #   - the chosen chat model
    #   - the Helper's model, when the Helper is on (it works on every message)
    #   - the Eyes' model, when Eyes is on
    #   - the embedding model (small, and used for every memory search)
    # With "None" chosen (model ""), nothing is kept: all RAM is freed.
    keep = set()
    if req.model:
        keep = {req.model, EMBED_MODEL}
        for model in [await settings.helper_model(), await settings.eyes_model()]:
            if model:
                keep.add(model)
    keep = {full_name(name) for name in keep}

    unloaded = []
    for name in await loaded_models():
        if full_name(name) not in keep:
            await unload(name)
            unloaded.append(name)
    return {"unloaded": unloaded}
