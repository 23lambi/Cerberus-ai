import json
import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel


app= FastAPI()

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL="llama3.2"
SYSTEM_PROMPT=(
    "You are Cerberus, a loyal guardian AI that runs privately"
    "On the user own computer. You are helpful, friendly and honest"
)


class Message(BaseModel):
    role:str
    content:str


class ChatRequest(BaseModel):
    messages:list[Message]



@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.get("/about")
def about():
    return{"name":"Cerberus" , "Version":"0.0.5"}


@app.post("/chat")
async def chat(req:ChatRequest):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [m.model_dump() for m in req.messages]

    async def generate():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                OLLAMA_URL,
                json={"model": MODEL, "messages": messages, "stream": True},
            ) as response:
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    yield chunk.get("message", {}).get("content", "")
                    if chunk.get("done"):
                        break   
    return StreamingResponse(generate(),media_type="text/plain")
