# POST /council: "Deep think". The model answers in three steps:
# a draft, a review of its own draft, then a final answer that fixes
# what the review found. Slower, but often better on hard questions.
# It uses the same brain as normal chat (context.py), so every step
# knows the memories, documents and project notes too.

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from cerberus import context, database
from cerberus.config import HEAD_MAX_TOKENS, JUDGE_MAX_TOKENS
from cerberus.ollama import OllamaError, stream_chat
from cerberus.prompts import DEEP_THINK
from cerberus.schemas import ChatRequest

router = APIRouter()


def event(step, text):
    # The page needs to know which step each piece belongs to, so every
    # piece is sent as one line of JSON: {"step": "draft", "text": "..."}
    # This format is called NDJSON (newline-delimited JSON).
    return json.dumps({"step": step, "text": text}) + "\n"


@router.post("/council")
async def council(req: ChatRequest):
    ctx = await context.prepare(req)
    question = ctx.question
    # Steps 2 and 3 don't see the chat, so their brain gets this
    # question's notes (memories, documents) right in the system prompt.
    brain = ctx.system_prompt + ("\n" + ctx.notes if ctx.notes else "")

    async def generate():
        draft = review = final = ""  # three variables, all set to ""
        if ctx.seen:
            yield event("seen", ctx.seen)  # what the Eyes saw, for the page
        try:
            # Step 1: the brain writes a draft, seeing the whole conversation.
            messages = ctx.messages(extra=DEEP_THINK["draft"])
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

        # Only the question and the final answer are saved, not the steps.
        if req.chat_id:
            database.save_message(req.chat_id, "user", question, ctx.images, ctx.seen)
            database.save_message(req.chat_id, "assistant", final)

    return StreamingResponse(
        generate(), media_type="application/x-ndjson", headers=ctx.headers()
    )
