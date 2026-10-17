# The page itself, plus small info URLs.

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from cerberus import settings
from cerberus.config import EMBED_MODEL
from cerberus.ollama import OllamaError, can_chat, can_see, can_think, list_models
from cerberus.ollama import full_name, loaded_models, unload

router = APIRouter()


@router.get("/")
def home():
    # Opening http://127.0.0.1:8000/ sends the whole app: one HTML page.
    # The page then loads its CSS and JS from /static.
    return FileResponse("static/index.html")


@router.get("/about")
def about():
    return {"name": "Cerberus", "version": "0.2.1"}


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
        return {"models": names, "thinking": thinking, "vision": vision}
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
