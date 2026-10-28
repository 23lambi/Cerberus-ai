# POST /research: the research agent (cerberus/research.py). It uses the
# same lifecycle as chat and Deep think (turns.py): the same checks, Stop,
# and the question and report saved together as one turn.

from contextlib import aclosing

from fastapi import APIRouter

from cerberus.search import research as agent
from cerberus.chat import turns
from cerberus.core.schemas import ChatRequest

router = APIRouter()


@router.post("/research")
async def research(req: ChatRequest):
    # The agent searches by itself, step by step, so the normal Web search
    # before the answer (context.py) is switched off.
    req = req.model_copy(update={"web": False})

    async def produce(ctx):
        async with aclosing(agent.run(ctx, req.model, req.chat_id)) as steps:
            async for item in steps:
                yield item

    return await turns.respond(req, produce)
