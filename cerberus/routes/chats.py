# The chat list in the sidebar: create, list, open and delete chats.

from fastapi import APIRouter, HTTPException

from cerberus import database
from cerberus.schemas import ChatTitle, NewChat

# prefix="/chats": every URL below starts with /chats.
router = APIRouter(prefix="/chats")


@router.post("")
def create_chat(body: NewChat):
    return database.create_chat(body.title, body.project_id)


@router.get("")
def list_chats(project_id: int | None = None, q: str = ""):
    # /chats lists normal chats, /chats?project_id=3 lists project 3's chats.
    # Add &q=python to keep only the chats that mention "python".
    return {"chats": database.list_chats(project_id, q.strip())}


# {chat_id} in the URL becomes the chat_id argument; ": int" makes FastAPI
# check it's a number (/chats/abc gets a 422 error).
@router.get("/{chat_id}")
def get_chat(chat_id: int):
    chat = database.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


# PUT changes something that already exists: here, the chat's title.
@router.put("/{chat_id}")
def rename_chat(chat_id: int, body: ChatTitle):
    title = body.title.strip()[:80]
    if not title:
        raise HTTPException(status_code=400, detail="A chat needs a title.")
    if not database.set_chat_title(chat_id, title):
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"id": chat_id, "title": title}


@router.delete("/{chat_id}")
def delete_chat(chat_id: int):
    database.delete_chat(chat_id)
    return {"deleted": chat_id}


# Regenerate: the page deletes the last question and answer, then sends
# the same question again. The new answer is saved like any other.
@router.delete("/{chat_id}/last-turn")
def delete_last_turn(chat_id: int):
    if not database.delete_last_turn(chat_id):
        raise HTTPException(status_code=404, detail="Nothing to delete")
    return {"deleted": chat_id}
