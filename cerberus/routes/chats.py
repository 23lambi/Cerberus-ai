# The chat list in the sidebar: create, list, open and delete chats.

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response

from cerberus import database, turns, keeper
from cerberus.schemas import ChatTitle, NewChat

# prefix="/chats": every URL below starts with /chats.
router = APIRouter(prefix="/chats")


@router.post("")
def create_chat(body: NewChat):
    if body.project_id and database.get_project(body.project_id) is None:
        raise HTTPException(404, "Project not found")
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
    chat["documents"] = [{"id": d["id"], "name": d["name"]} for d in database.chat_documents(chat_id)]
    chat["answering"] = chat_id in turns.active
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
    turns.require_idle(chat_id)
    for doc in database.chat_documents(chat_id):
        keeper.delete_document(doc["id"])
    database.delete_chat(chat_id)
    return {"deleted": chat_id}


# Regenerate: the page deletes the last question and answer, then sends
# the same question again. The new answer is saved like any other.
@router.delete("/{chat_id}/last-turn")
def delete_last_turn(chat_id: int):
    turns.require_idle(chat_id)
    if not database.delete_last_turn(chat_id):
        raise HTTPException(status_code=404, detail="Nothing to delete")
    return {"deleted": chat_id}


@router.post("/{chat_id}/stop")
async def stop_chat(chat_id: int):
    if chat_id in turns.active:
        turns.active[chat_id].set()
    return {"stopping": chat_id in turns.active}


@router.get("/{chat_id}/export")
def export_chat(chat_id: int, format: str = "markdown"):
    chat = database.get_chat(chat_id)
    if chat is None:
        raise HTTPException(404, "Chat not found")
    if format == "json":
        return JSONResponse(chat, headers={"Content-Disposition": f'attachment; filename="cerberus-chat-{chat_id}.json"'})
    if format != "markdown":
        raise HTTPException(400, "Choose markdown or json.")
    parts = ["# " + chat["title"]]
    for message in chat["messages"]:
        parts.append("## " + ("You" if message["role"] == "user" else "Cerberus"))
        parts.append(message["content"])
        if message["seen"]:
            parts.append("Image description:\n\n" + message["seen"])
        for image in message["images"]:
            parts.append(f"![Attached image](data:image/jpeg;base64,{image})")
    return Response("\n\n".join(parts) + "\n", media_type="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="cerberus-chat-{chat_id}.md"'})
