from contextlib import aclosing

# POST /council: "Deep think". The model answers in three steps:
# a draft, a review of its own draft, then a final answer that fixes
# what the review found. Slower, but often better on hard questions.
# It uses the same brain as normal chat (context.py), so every step
# knows the memories, documents and project notes too.

from fastapi import APIRouter

from cerberus import turns
from cerberus.config import HEAD_MAX_TOKENS, JUDGE_MAX_TOKENS
from cerberus.ollama import stream_chat
from cerberus.prompts import DEEP_THINK
from cerberus.schemas import ChatRequest

router = APIRouter()


@router.post("/council")
async def council(req: ChatRequest):
    async def produce(ctx):
        question = ctx.question
        brain = ctx.system_prompt + ("\n" + ctx.notes if ctx.notes else "")
        if ctx.sources:
            brain += "\n" + ctx.source_prompt()
        draft = review = ""
        if ctx.seen:
            yield {"step": "seen", "text": ctx.seen}
        messages = ctx.messages(extra=DEEP_THINK["draft"])
        async with aclosing(stream_chat(req.model, messages, HEAD_MAX_TOKENS)) as events:
            async for piece in events:
                draft += piece
                yield {"step": "draft", "text": piece}

        check = f"Question:\n{question}\n\nDraft:\n{draft}\n"
        messages = [
            {"role": "system", "content": brain + "\n" + DEEP_THINK["review"]},
            {"role": "user", "content": check},
        ]
        async with aclosing(stream_chat(req.model, messages, HEAD_MAX_TOKENS)) as events:
            async for piece in events:
                review += piece
                yield {"step": "review", "text": piece}

        messages = [
            {"role": "system", "content": brain + "\n" + DEEP_THINK["final"]},
            {"role": "user", "content": check + f"\nReview:\n{review}\n"},
        ]
        async with aclosing(stream_chat(req.model, messages, JUDGE_MAX_TOKENS)) as events:
            async for piece in events:
                yield {"step": "final", "text": piece}

    return await turns.respond(req, produce)
