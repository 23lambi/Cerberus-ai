from fastapi import APIRouter
from pydantic import BaseModel

from cerberus import guard

router = APIRouter()


class GuardRequest(BaseModel):
    message: str
    model: str


@router.post("/guard")
async def check(req: GuardRequest):
    head, decided_by = await guard.route(req.message, req.model)
    return {"head": head, "decided_by": decided_by}
