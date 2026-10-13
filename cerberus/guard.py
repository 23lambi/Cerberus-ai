import re

from cerberus.config import GUARD_USE_MODEL
from cerberus.ollama import OllamaError, stream_chat
from cerberus.prompts import GUARD_PROMPT

HEADS = ("talk", "remember", "do")

# Checked in this order. The first rule that matches wins.
RULES = [
    ("do", r"\bremind me\b|\breminder\b|\bremember to\b|\bto-?dos?\b"),
    ("do", r"\btasks?\b|\bschedule\b|\bdon'?t let me forget\b|\bplan (my|a|the)\b"),
    ("remember", r"\bremember\b|\bforget (that|this|about)\b|\blast time\b"),
    ("remember", r"\bwhat did (i|we)\b|\bwhat do you know about me\b"),
    ("remember", r"\bmy (notes|documents?|files?)\b"),
    ("remember", r"\bwe (talked|discussed|decided|said)\b"),
    ("remember", r"\bin (the|my) (pdf|document|file|notes)\b"),
]


def by_rules(message):
    text = message.lower()
    for head, pattern in RULES:
        if re.search(pattern, text):
            return head
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
        if word in HEADS:
            return word
    return None


async def route(message, model):
    head = by_rules(message)
    if head:
        return head, "rules"

    if GUARD_USE_MODEL:
        head = await by_model(message, model)
        if head:
            return head, "model"

    return "talk", "default"
