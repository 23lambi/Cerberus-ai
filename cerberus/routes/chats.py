from fastapi import APIRouter, HTTPException

from cerberus import database
from cerberus.schemas import NewChat

router = APIRouter(prefix="/chats")


@router.post("")
def create_chat(body: NewChat):
    return database.create_chat(body.title)


@router.get("")
def list_chats():
    return {"chats": database.list_chats()}


@router.get("/{chat_id}")
def get_chat(chat_id: int):
    chat = database.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@router.delete("/{chat_id}")
def delete_chat(chat_id: int):
    database.delete_chat(chat_id)
    return {"deleted": chat_id}
