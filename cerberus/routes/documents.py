from fastapi import APIRouter, HTTPException, Request

from cerberus import keeper
from cerberus.config import MAX_UPLOAD_MB

router = APIRouter(prefix="/documents")


@router.get("")
def list_documents():
    return {"documents": keeper.list_documents()}


@router.post("")
async def upload_document(request: Request, name: str):
    data = await request.body()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Files can be up to {MAX_UPLOAD_MB} MB.")
    try:
        return await keeper.add_document(name, data)
    except keeper.DocumentError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None


@router.delete("/{document_id}")
def delete_document(document_id: int):
    if not keeper.delete_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": document_id}
