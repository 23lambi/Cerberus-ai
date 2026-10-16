from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from cerberus import database, guard, keeper, settings, summary
from cerberus.ollama import ERROR_MARK, OllamaError, stream_chat, trim_history
from cerberus.prompts import KEEPER_RECALL, KEEPER_SAVED, SUMMARY_NOTE
from cerberus.schemas import ChatRequest

router = APIRouter()


@router.post("/chat")
async def chat(req: ChatRequest):
    all_messages = [m.model_dump() for m in req.messages]
    history = trim_history(all_messages)
    question = history[-1]["content"]

    # Whatever trim_history dropped gets summarized instead of forgotten.
    old = all_messages[: len(all_messages) - len(history)]
    earlier = await summary.old_part(req.chat_id, old, req.model)

    # The Guard only decides one thing: does this need memory?
    mode, _ = await guard.route(question, req.model)
    memory_mode = mode == "memory"
    system_prompt = settings.brain()

    # Memory: save new memories, then find what matters for this question.
    saved = keeper.wants_to_save(question) if memory_mode else None
    if saved:
        await keeper.add(saved)

    found = await keeper.recall(question, keeper_mode=memory_mode, chat_id=req.chat_id)
    context = keeper.context_prompt(found)
    if context:
        system_prompt += "\n" + context
    if saved:
        system_prompt += "\n" + KEEPER_SAVED.format(text=saved)
    elif memory_mode:
        system_prompt += "\n" + KEEPER_RECALL
    if earlier:
        system_prompt += "\n" + SUMMARY_NOTE.format(text=earlier)

    messages = [{"role": "system", "content": system_prompt}] + history

    async def generate():
        reply = ""
        failed = False
        try:
            async for piece in stream_chat(req.model, messages):
                reply += piece
                yield piece
        except OllamaError as error:
            failed = True
            yield f"\n{ERROR_MARK} {error}"
        finally:
            # Runs at the end, and also when the user presses Stop.
            if req.chat_id and reply and not failed:
                database.save_message(req.chat_id, "user", question)
                database.save_message(req.chat_id, "assistant", reply)

    return StreamingResponse(
        generate(),
        media_type="text/plain",
        headers={
            "X-Cerberus-Mode": mode,
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
