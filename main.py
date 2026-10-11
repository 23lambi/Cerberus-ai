from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel 

app = FastAPI()

class ChatMessage(BaseModel):
    message: str

@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.post("/chat")
def chat(msg:ChatMessage):
    return{"reply":f"Cerberus heard:{msg.message}"}



