from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from cerberus.database import init_db
from cerberus.routes import (
    chat,
    chats,
    council,
    documents,
    guard,
    memories,
    pages,
    projects,
    settings,
)

init_db()

app = FastAPI(title="Cerberus")

app.include_router(pages.router)
app.include_router(chat.router)
app.include_router(council.router)
app.include_router(chats.router)
app.include_router(projects.router)
app.include_router(settings.router)
app.include_router(guard.router)
app.include_router(memories.router)
app.include_router(documents.router)

app.mount("/static", StaticFiles(directory="static"), name="static")
