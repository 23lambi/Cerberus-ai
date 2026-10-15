from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from cerberus import database, guard, keeper, settings
from cerberus.ollama import ERROR_MARK, OllamaError, stream_chat, trim_history
from cerberus.prompts import HEAD_NOT_READY, KEEPER_RECALL, KEEPER_SAVED
from cerberus.schemas import ChatRequest


from fastapi import HTTPException
from pydantic import BaseModel

router = APIRouter()


@router.post("/chat")
async def chat(req: ChatRequest):
    history = trim_history([m.model_dump() for m in req.messages])
    question = history[-1]["content"]

    head, _ = await guard.route(question, req.model)
    system_prompt = settings.get("system_prompt")

    # The Keeper: save new memories, then find what matters for this question.
    saved = keeper.wants_to_save(question) if head == "remember" else None
    if saved:
        await keeper.add(saved)

    found = await keeper.recall(
        question, keeper_mode=(head == "remember"), chat_id=req.chat_id
    )
    context = keeper.context_prompt(found)
    if context:
        system_prompt += "\n" + context
    if saved:
        system_prompt += "\n" + KEEPER_SAVED.format(text=saved)
    elif head == "remember":
        system_prompt += "\n" + KEEPER_RECALL
    if head in HEAD_NOT_READY:
        system_prompt += "\n" + HEAD_NOT_READY[head]

    messages = [{"role": "system", "content": system_prompt}] + history

    async def generate():
        reply = ""
        failed= False

        try:
            async for piece in stream_chat(req.model, messages):
                reply+= piece
                yield piece
        except OllamaError as error:
            failed =True
            yield f"\n{ERROR_MARK} {error}"
        finally:
            if req.chat_id and reply and not failed:
                database.save_message(req.chat_id, "user",question)
                database.save_message(req.chat_id,"assistant",reply)


    return StreamingResponse(
        generate(),
        media_type="text/plain",
        headers={
            "X-Cerberus-Head": head,
            "X-Cerberus-Memories": str(len(found["memories"])),
            "X-Cerberus-Documents": str(len(found["documents"])),
            "X-Cerberus-Chats": str(len(found["chats"])),
        },
    )


class TitleRequest(BaseModel):
    model: str


@router.post("/chats/{chat_id}/title")
async def make_title(chat_id: int, req: TitleRequest):
    chat = database.get_chat(chat_id)
    if chat is None or len(chat["messages"]) < 2:
        raise HTTPException(status_code=404, detail="Nothing to title yet")

    question = chat["messages"][0]["content"]
    answer = chat["messages"][1]["content"][:500]
    prompt = (
        "Write a short title, at most 5 words, for a chat that starts like this. "
        "Reply with only the title, no quotes.\n\n"
        f"User: {question}\nAssistant: {answer}"
    )

    title = ""
    try:
        async for piece in stream_chat(req.model, [{"role": "user", "content": prompt}]):
            title += piece
    except OllamaError:
        return {"title": chat["title"]}  # keep the placeholder

    title = title.strip().splitlines()[0].strip(' "\'.')[:60] if title.strip() else ""
    if title:
        database.set_chat_title(chat_id, title)
    return {"title": title or chat["title"]}
