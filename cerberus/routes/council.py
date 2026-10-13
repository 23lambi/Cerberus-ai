import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from cerberus import database, settings
from cerberus.config import HEAD_MAX_TOKENS, JUDGE_MAX_TOKENS
from cerberus.ollama import OllamaError, stream_chat, trim_history
from cerberus.schemas import ChatRequest

router = APIRouter()


def event(head, text):
    return json.dumps({"head": head, "text": text}) + "\n"


@router.post("/council")
async def council(req: ChatRequest):
    history = trim_history([m.model_dump() for m in req.messages])
    question = history[-1]["content"]

    async def generate():
        answers = {}
        try:
            for name in ["thinker", "coder"]:
                answers[name] = ""
                prompt = settings.get(f"{name}_prompt")
                messages = [{"role": "system", "content": prompt}] + history
                async for piece in stream_chat(req.model, messages, HEAD_MAX_TOKENS):
                    answers[name] += piece
                    yield event(name, piece)

            review_request = f"""
Question:
{question}

Thinker's answer:
{answers["thinker"]}

Coder's answer:
{answers["coder"]}
"""
            answers["critic"] = ""
            messages = [
                {"role": "system", "content": settings.get("critic_prompt")},
                {"role": "user", "content": review_request},
            ]
            async for piece in stream_chat(req.model, messages, HEAD_MAX_TOKENS):
                answers["critic"] += piece
                yield event("critic", piece)

            judge_request = review_request + f"""
Critic's review:
{answers["critic"]}
"""
            messages = [
                {"role": "system", "content": settings.get("judge_prompt")},
                {"role": "user", "content": judge_request},
            ]
            answers["judge"] = ""
            async for piece in stream_chat(req.model, messages, JUDGE_MAX_TOKENS):
                answers["judge"] += piece
                yield event("judge", piece)

        except OllamaError as error:
            yield event("error", str(error))
            return

        if req.chat_id:
            database.save_message(req.chat_id, "user", question)
            database.save_message(req.chat_id, "assistant", answers["judge"])

    return StreamingResponse(generate(), media_type="application/x-ndjson")
