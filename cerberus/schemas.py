# The shapes of the JSON the browser sends. FastAPI checks every request
# against these classes: a missing field or a wrong type gets an automatic
# 422 error, so the rest of the code can trust the data.

import base64
import binascii
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]
ModelName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=100000)
    images: list[str] = Field(default_factory=list, max_length=4)
    seen: str = Field(default="", max_length=10000)

    @model_validator(mode="after")
    def valid_message(self):
        if not self.content.strip() and not self.images:
            raise ValueError("A message needs text or an image.")
        if self.role != "user" and (self.images or self.seen):
            raise ValueError("Only user messages may contain images or image descriptions.")
        for encoded in self.images:
            if len(encoded) > 4 * 1024 * 1024:
                raise ValueError("Each image must be at most 3 MB.")
            try:
                if not base64.b64decode(encoded, validate=True):
                    raise ValueError("An image cannot be empty.")
            except (binascii.Error, ValueError):
                raise ValueError("Images must contain valid base64 data.") from None
        return self


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=2000)
    model: ModelName
    chat_id: int | None = Field(default=None, gt=0)
    think: bool = False  # let a thinking model reason first (normal chat only)
    tools: bool = False  # let the model use tools (calculator, memory search...)

    @model_validator(mode="after")
    def valid_conversation(self):
        for index, message in enumerate(self.messages):
            expected = "user" if index % 2 == 0 else "assistant"
            if message.role != expected:
                raise ValueError("Messages must alternate between user and assistant, starting with user.")
        if self.messages[-1].role != "user":
            raise ValueError("The last message must be from the user.")
        if sum(len(m.content) + len(m.seen) + sum(map(len, m.images)) for m in self.messages) > 24 * 1024 * 1024:
            raise ValueError("This conversation is too large. Start a new chat.")
        return self


class NewChat(BaseModel):
    title: NonBlank = "New chat"
    project_id: int | None = Field(default=None, gt=0)


class ChatTitle(BaseModel):
    title: str


class MemoryIn(BaseModel):
    text: NonBlank


class ProjectIn(BaseModel):
    name: str
