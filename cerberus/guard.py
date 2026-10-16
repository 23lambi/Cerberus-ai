import re

from cerberus.config import GUARD_USE_MODEL
from cerberus.ollama import OllamaError, stream_chat
from cerberus.prompts import GUARD_PROMPT

MODES = ("chat", "memory")

# If any of these match, the message needs Cerberus's memory.
MEMORY_RULES = [
    r"\bremember\b|\bforget (that|this|about)\b|\blast time\b",
    r"\bwhat did (i|we)\b|\bwhat do you know about me\b",
    r"\bmy (notes|documents?|files?)\b",
    r"\bwe (talked|discussed|decided|said)\b",
    r"\bin (the|my) (pdf|document|file|notes)\b",
]


def by_rules(message):
    text = message.lower()
    for pattern in MEMORY_RULES:
        if re.search(pattern, text):
            return "memory"
    return None


async def by_model(message, model):
    messages = [
        {"role": "system", "content": GUARD_PROMPT},
        {"role": "user", "content": message},
    ]
    answer = ""
    try:
        async for piece in stream_chat(model, messages, max_tokens=5, temperature=0):
            answer += piece
    except OllamaError:
        return None

    for word in re.findall(r"[a-z]+", answer.lower()):
        if word in MODES:
            return word
    return None


async def route(message, model):
    mode = by_rules(message)
    if mode:
        return mode, "rules"

    if GUARD_USE_MODEL:
        mode = await by_model(message, model)
        if mode:
            return mode, "model"

    return "chat", "default"
