# POST /guard: ask the Guard how it would sort a message, without chatting.
# Handy for testing the rules, for example at http://127.0.0.1:8000/docs

from fastapi import APIRouter
from pydantic import BaseModel

from cerberus import guard

router = APIRouter()


class GuardRequest(BaseModel):
    message: str
    model: str


@router.post("/guard")
async def check(req: GuardRequest):
    mode, decided_by = await guard.route(req.message, req.model)
    return {"mode": mode, "decided_by": decided_by}
