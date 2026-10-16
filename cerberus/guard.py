# The Guard decides one thing for every message: is it normal "chat",
# or does it need Cerberus's "memory" (things saved about the user,
# documents, earlier chats)? It tries fast rules first and only asks
# the model when the rules can't tell.

import re  # regular expressions: patterns for finding text

from cerberus.config import GUARD_USE_MODEL
from cerberus.ollama import OllamaError, can_think, stream_chat
from cerberus.prompts import GUARD_PROMPT

MODES = ("chat", "memory")
SHORT_REPLY_WORDS = 3

# If any of these match, the message needs Cerberus's memory.
# \b is a word boundary, so "remember" doesn't match inside "remembered".
# | means "or".
MEMORY_RULES = [
    r"\bremember\b|\bforget (that|this|about)\b|\blast time\b",
    r"\bwhat did (i|we)\b|\bwhat do you know about me\b",
    r"\bmy (notes|documents?|files?)\b",
    r"\bwe (talked|discussed|decided|said)\b",
    r"\bin (the|my) (pdf|document|file|notes)\b",
]


def by_rules(message):
    # Returns "memory" when a rule matches, None when the rules don't know.
    text = message.lower()
    for pattern in MEMORY_RULES:
        if re.search(pattern, text):
            return "memory"
    return None


async def by_model(message, model):
    # Ask the model for one word. max_tokens=5 keeps it short, and
    # temperature=0 makes it give the same answer every time.
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

    # Models don't always obey "one word", so look for the first valid
    # word anywhere in the answer, like in "Memory." or "mode: chat".
    for word in re.findall(r"[a-z]+", answer.lower()):
        if word in MODES:
            return word
    return None


async def route(message, model, use_model=True):
    # Returns (mode, who decided), like ("memory", "rules").
    # use_model=False: only the rules decide, no model is asked.
    mode = by_rules(message)
    if mode:
        return mode, "rules"

    # Short replies like "yes", "ok" or "go on" have no topic of their own,
    # so they stay in chat without asking the model.
    if len(message.split()) <= SHORT_REPLY_WORDS:
        return "chat", "rules"

    # A thinking model would think for many seconds before every single
    # message, just to say one word. Not worth it: the rules decide alone.
    if use_model and GUARD_USE_MODEL and not await can_think(model):
        mode = await by_model(message, model)
        if mode:
            return mode, "model"

    # Nobody could tell, so use the safe choice.
    return "chat", "default"
