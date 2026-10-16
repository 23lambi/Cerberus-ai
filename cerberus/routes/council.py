import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from cerberus import database, settings
from cerberus.config import HEAD_MAX_TOKENS, JUDGE_MAX_TOKENS
from cerberus.ollama import OllamaError, stream_chat, trim_history
from cerberus.prompts import DEEP_THINK
from cerberus.schemas import ChatRequest

router = APIRouter()


def event(step, text):
    return json.dumps({"step": step, "text": text}) + "\n"


@router.post("/council")
async def council(req: ChatRequest):
    history = trim_history([m.model_dump() for m in req.messages])
    question = history[-1]["content"]
    brain = settings.brain()

    async def generate():
        draft = review = final = ""
        try:
            # Step 1: the brain writes a draft, seeing the whole conversation.
            messages = [{"role": "system", "content": brain + "\n" + DEEP_THINK["draft"]}] + history
            async for piece in stream_chat(req.model, messages, HEAD_MAX_TOKENS):
                draft += piece
                yield event("draft", piece)

            # Step 2: the same brain checks its own draft.
            check = f"Question:\n{question}\n\nDraft:\n{draft}\n"
            messages = [
                {"role": "system", "content": brain + "\n" + DEEP_THINK["review"]},
                {"role": "user", "content": check},
            ]
            async for piece in stream_chat(req.model, messages, HEAD_MAX_TOKENS):
                review += piece
                yield event("review", piece)

            # Step 3: the final answer, with the review's fixes.
            messages = [
                {"role": "system", "content": brain + "\n" + DEEP_THINK["final"]},
                {"role": "user", "content": check + f"\nReview:\n{review}\n"},
            ]
            async for piece in stream_chat(req.model, messages, JUDGE_MAX_TOKENS):
                final += piece
                yield event("final", piece)

        except OllamaError as error:
            yield event("error", str(error))
            return

        if req.chat_id:
            database.save_message(req.chat_id, "user", question)
            database.save_message(req.chat_id, "assistant", final)

    return StreamingResponse(generate(), media_type="application/x-ndjson")
