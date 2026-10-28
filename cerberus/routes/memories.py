# The Memories tab: list, add, edit and forget memories.
# The four URLs follow REST: GET reads, POST adds, PUT changes, DELETE removes.

from fastapi import APIRouter, HTTPException

from cerberus.storage import keeper
from cerberus.core.schemas import MemoryIn

router = APIRouter(prefix="/memories")


@router.get("")
def list_memories():
    return {"memories": keeper.list_all()}


# async, because adding a memory waits for Ollama to make its embedding.
@router.post("")
async def add_memory(body: MemoryIn):
    return await keeper.add(body.text.strip())


@router.put("/{memory_id}")
async def update_memory(memory_id: int, body: MemoryIn):
    if not await keeper.update(memory_id, body.text.strip()):
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"id": memory_id, "text": body.text.strip()}


@router.delete("/{memory_id}")
def delete_memory(memory_id: int):
    if not keeper.delete(memory_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"deleted": memory_id}
