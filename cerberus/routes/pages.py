from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from cerberus.ollama import OllamaError, list_models

router = APIRouter()


@router.get("/")
def home():
    return FileResponse("static/index.html")


@router.get("/about")
def about():
    return {"name": "Cerberus", "version": "0.2.1"}


@router.get("/models")
async def models():
    try:
        return {"models": await list_models()}
    except OllamaError as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
