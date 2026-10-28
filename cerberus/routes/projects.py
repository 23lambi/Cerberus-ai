# Projects: groups of chats that share notes (see recap.py).

from fastapi import APIRouter, HTTPException

from cerberus import database, keeper, turns
from cerberus.schemas import ProjectIn

router = APIRouter(prefix="/projects")


def clean_name(body):
    # Never trust the browser: check the name here too, not only in the page.
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="A project needs a name.")
    return name[:80]


@router.get("")
def list_projects():
    return {"projects": database.list_projects()}


@router.post("")
def create_project(body: ProjectIn):
    return database.create_project(clean_name(body))


@router.put("/{project_id}")
def rename_project(project_id: int, body: ProjectIn):
    name = clean_name(body)
    if not database.rename_project(project_id, name):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"id": project_id, "name": name}


@router.delete("/{project_id}")
def delete_project(project_id: int):
    for chat in database.list_chats(project_id):
        turns.require_idle(chat["id"])
    for chat in database.list_chats(project_id):
        for doc in database.chat_documents(chat["id"]):
            keeper.delete_document(doc["id"])
    for doc in database.list_documents(project_id):
        keeper.delete_document(doc["id"])
    if not database.delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"deleted": project_id}
