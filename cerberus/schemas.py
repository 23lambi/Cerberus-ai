

from pydantic import BaseModel


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    model: str
    chat_id: int | None=None


class NewChat(BaseModel):
    title: str ="New chat"





class MemoryIn(BaseModel):
    text: str
