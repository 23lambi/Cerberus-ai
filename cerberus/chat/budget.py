"""Estimate prompt space without downloading a tokenizer for every local model.

These are conservative estimates, not exact model token counts. Ollama's
reported counts remain the source of truth displayed below an answer.
"""

import json
import math

from cerberus.core.config import NUM_CTX


class ContextTooLarge(ValueError):
    pass


def estimate(messages, tools=None):
    total = 32
    for message in messages:
        total += 16 + math.ceil(len(message.get("content", "").encode("utf-8")) / 3)
        total += 1024 * len(message.get("images", []))
        if message.get("tool_calls"):
            total += math.ceil(len(json.dumps(message["tool_calls"]).encode("utf-8")) / 3)
    if tools:
        total += math.ceil(len(json.dumps(tools).encode("utf-8")) / 3)
    return total


def fit(messages, max_tokens, tools=None, num_ctx=NUM_CTX):
    """Drop oldest complete turns; always retain instructions and the new question.

    Tool requests/results belong to the latest turn and are kept together.
    An oversized current turn fails clearly instead of silently losing its text.
    """
    messages = list(messages)
    limit = num_ctx - max_tokens - 256
    while estimate(messages, tools) > limit:
        users = [i for i, m in enumerate(messages) if m["role"] == "user"]
        if len(users) < 2:
            raise ContextTooLarge(
                "This message and its context exceed the model's context budget. "
                "Shorten the message, remove some attached files or images, turn Think off, or start a new chat."
            )
        del messages[users[0]:users[1]]
    return messages
