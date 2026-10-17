# The shapes of the JSON the browser sends. FastAPI checks every request
# against these classes: a missing field or a wrong type gets an automatic
# 422 error, so the rest of the code can trust the data.

from pydantic import BaseModel


class Message(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    images: list[str] = []  # pictures as base64 text (only on user messages)
    seen: str = ""  # what the Eyes saw in those pictures, as text


class ChatRequest(BaseModel):
    messages: list[Message]  # the whole conversation so far
    model: str  # the Ollama model name, like "qwen3-coder:30b"
    chat_id: int | None = None  # None = don't save this chat
    think: bool = False  # let a thinking model reason first (normal chat only)
    tools: bool = False  # let the model use tools (calculator, memory search...)


class NewChat(BaseModel):
    title: str = "New chat"
    project_id: int | None = None  # None = a normal chat, not in a project


class ChatTitle(BaseModel):
    title: str


class MemoryIn(BaseModel):
    text: str


class ProjectIn(BaseModel):
    name: str
