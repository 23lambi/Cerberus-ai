# Builds everything the model needs before it answers. Normal chat
# (routes/chat.py) and Deep think (routes/council.py) both call prepare(),
# so they share one brain. Change it here and both get the change.
#
# Speed matters here. Ollama remembers the prompt it read last (a "prompt
# cache"), and next time it only reads what changed AFTER the first
# difference. So the order of the prompt is important:
#   1. system prompt: things that rarely change (personality, project
#      notes, summary of old messages)
#   2. the chat history, which only grows at the end
#   3. the newest message, with this question's notes (memories and
#      documents found) put in front of it
# If the notes were in the system prompt, the very start would change on
# every message and the model would re-read the whole chat each time.
# Measured on a CPU: 68.8 s before, 3.0 s after.

from dataclasses import dataclass

from cerberus import guard, keeper, recap, settings, summary
from cerberus.eyes import describe
from cerberus.ollama import can_see, trim_history
from cerberus.prompts import (
    CONTEXT_NOTE,
    KEEPER_NOTHING,
    KEEPER_RECALL,
    KEEPER_SAVED,
    SEEN_NOTE,
    SUMMARY_NOTE,
    UNSEEN_NOTE,
)


# A dataclass is a class that only holds data. Python writes the __init__
# for us from the fields below, so Context(question=..., history=..., ...)
# just works, and we can read ctx.question instead of ctx["question"].
@dataclass
class Context:
    question: str  # the user's newest message
    history: list  # the newest messages, exactly as the user wrote them
    system_prompt: str  # the stable part: personality, project notes, summary
    notes: str  # this question's part: memories and documents found ("" = none)
    mode: str  # "chat" or "memory", from the Guard
    found: dict  # what the Keeper found: memories, documents, chats
    images: list  # the pictures sent with the question, to save with it
    seen: str  # what the Eyes saw in them ("" = nothing to describe)
    eyes: str | None  # the vision model that looked just now, or None

    def messages(self, extra=""):
        # The full list for Ollama. extra is added to the system prompt
        # (Deep think uses it for "step 1 of 3").
        history = list(self.history)  # a copy, so self.history stays plain
        if self.notes:
            last = history[-1]
            # {**last, ...} = a copy of the dict with "content" replaced.
            history[-1] = {
                **last,
                "content": CONTEXT_NOTE.format(notes=self.notes, question=last["content"]),
            }
        system = self.system_prompt + ("\n" + extra if extra else "")
        return [{"role": "system", "content": system}] + history

    def headers(self):
        # Headers arrive before the answer, so the page can already show
        # the mode and what was found ("Memory, 2 memories").
        headers = {
            "X-Cerberus-Mode": self.mode,
            "X-Cerberus-Memories": str(len(self.found["memories"])),
            "X-Cerberus-Documents": str(len(self.found["documents"])),
            "X-Cerberus-Chats": str(len(self.found["chats"])),
        }
        if self.eyes:
            headers["X-Cerberus-Eyes"] = self.eyes
        return headers


def for_model(message, see):
    # The message the way Ollama wants it. A model that can see gets the
    # images; a model that can't gets what the Eyes saw, as text.
    clean = {"role": message["role"], "content": message["content"]}
    if message.get("images"):
        if see:
            clean["images"] = message["images"]
        elif message.get("seen"):
            clean["content"] += "\n\n" + SEEN_NOTE.format(text=message["seen"])
        else:
            # Say so plainly, or the model may pretend it can see the image.
            clean["content"] += "\n\n" + UNSEEN_NOTE
    return clean


async def prepare(req):
    # req is a ChatRequest: the messages, the model and the chat id.
    # model_dump() turns each pydantic Message into a plain dict.
    all_messages = [m.model_dump() for m in req.messages]
    newest = all_messages[-1]
    question = newest["content"]  # the newest message is the question
    see = await can_see(req.model)

    # Eyes: when the chat model can't see, a vision model describes the
    # new images. Older messages already carry their "seen" text, so it
    # never has to look at the same picture twice.
    eyes = None
    if newest["images"] and not see and not newest["seen"]:
        eyes = await settings.eyes_model()
        if eyes:
            newest["seen"] = await describe(eyes, newest["images"], question)

    history = [for_model(m, see) for m in trim_history(all_messages)]

    # Background jobs (summary, Guard) go to the Helper when it's on.
    helper = await settings.helper_model()
    jobs_model = helper or req.model

    # ---------- 1. The stable part: the system prompt ----------

    system_prompt = settings.brain()

    # Inside a project: add the notes from the project's other chats.
    project = recap.project_prompt(req.chat_id)
    if project:
        system_prompt += "\n" + project

    # Whatever trim_history dropped gets summarized instead of forgotten.
    old = all_messages[: len(all_messages) - len(history)]
    earlier = await summary.old_part(req.chat_id, old, jobs_model)
    if earlier:
        system_prompt += "\n" + SUMMARY_NOTE.format(text=earlier)

    # ---------- 2. This question's part: the notes ----------

    # The Guard only decides one thing: does this need memory? It only
    # asks a model when the Helper is on: a small, fast model sorts in
    # about a second, while a big chat model on a CPU can take 20.
    mode, _ = await guard.route(question, jobs_model, use_model=helper is not None)
    memory_mode = mode == "memory"

    # Memory: save new memories, then find what matters for this question.
    saved = keeper.wants_to_save(question) if memory_mode else None
    if saved:
        await keeper.add(saved)

    found = await keeper.recall(question, keeper_mode=memory_mode, chat_id=req.chat_id)
    parts = []
    context = keeper.context_prompt(found)
    if context:
        parts.append(context)
    # Tell the model what happened, so it answers honestly.
    if saved:
        parts.append(KEEPER_SAVED.format(text=saved).strip())
    elif memory_mode and (context or project):
        parts.append(KEEPER_RECALL.strip())
    elif memory_mode:
        # Nothing was found, so tell the model plainly instead of letting it guess.
        parts.append(KEEPER_NOTHING.strip())

    return Context(
        question=question,
        history=history,
        system_prompt=system_prompt,
        notes="\n\n".join(parts),
        mode=mode,
        found=found,
        images=newest["images"],
        seen=newest["seen"],
        eyes=eyes,
    )
