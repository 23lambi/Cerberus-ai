# The starting point of Cerberus. Run it with:  uvicorn main:app --reload
# "main:app" means: in the file main.py, use the object called app.

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from cerberus.config import STATIC_DIR
from cerberus.database import init_db

# Each route file is one group of URLs, for example everything under /chats.
from cerberus.routes import (
    backup,
    chat,
    chats,
    council,
    documents,
    guard,
    memories,
    pages,
    projects,
    reverse,
    settings,
)

# Create the tables in cerberus.db if they don't exist yet.
# This runs once, when the server starts.
init_db()

app = FastAPI(title="Cerberus")


# Middleware runs on every request: before it (code above call_next) and
# after it (code below). Here we add a header to the answer.
@app.middleware("http")
async def always_fresh(request, call_next):
    response = await call_next(request)
    # Without this, the browser keeps old copies of style.css and app.js and
    # you don't see your changes. "no-cache" doesn't mean "don't store": it
    # means "ask the server first". If the file didn't change, the server
    # answers "304 Not Modified" with no body, so this stays fast.
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# Plug every group of URLs into the app.
app.include_router(pages.router)
app.include_router(backup.router)
app.include_router(chat.router)
app.include_router(council.router)
app.include_router(chats.router)
app.include_router(projects.router)
app.include_router(settings.router)
app.include_router(guard.router)
app.include_router(memories.router)
app.include_router(documents.router)
app.include_router(reverse.router)

# Serve the files in the static folder (HTML, CSS, JS) at /static/...
# so the browser can download them.
# The full path, so it works from any folder (and in the desktop app).
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
