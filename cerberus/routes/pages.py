# The page itself, plus small info URLs.

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from cerberus.ollama import OllamaError, can_chat, can_think, list_models

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
        return {"models": names, "thinking": thinking}
    except OllamaError as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
