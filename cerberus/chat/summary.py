# Long chats: only the newest MAX_HISTORY_MESSAGES go to the model. The
# older ones would be forgotten, so instead we keep a short summary of
# them and add it to the system prompt.

from cerberus.storage import database
from cerberus.core.config import SUMMARY_EVERY
from cerberus.engines.ollama import OllamaError, stream_chat
from cerberus.chat.prompts import SUMMARY_PROMPT


def as_text(messages):
    # The messages as "User: ..." / "Cerberus: ..." lines. Each message is
    # cut at 600 characters so the summary prompt stays small.
    lines = []
    for message in messages:
        who = "User" if message["role"] == "user" else "Cerberus"
        lines.append(f"{who}: {message['content'][:600]}")
    return "\n".join(lines)


async def old_part(chat_id, old, model):
    """Return a summary of the messages that no longer fit, updating it when needed."""
    if not chat_id or not old:
        return ""

    # "covered" = how many of the old messages are already in the summary.
    saved = database.get_summary(chat_id)
    if saved is None or saved["covered"] > len(old):
        # No summary yet, or it covers more than exists (the chat was
        # changed), so start from scratch.
        saved = {"text": "", "covered": 0}

    new = old[saved["covered"]:]
    # Only redo the summary once enough new messages have fallen out.
    # Every summary is an extra model call, so we don't do it every message.
    if saved["text"] and len(new) < SUMMARY_EVERY:
        return saved["text"]

    # The model gets the old summary plus the new messages and writes an
    # updated summary. That way it never has to read the whole chat again.
    prompt = SUMMARY_PROMPT.format(
        previous=saved["text"] or "(nothing yet)", new=as_text(new)
    )
    text = ""
    try:
        async for piece in stream_chat(model, [{"role": "user", "content": prompt}]):
            text += piece
    except OllamaError:
        return saved["text"]  # keep the old summary rather than fail the chat

    text = text.strip()
    if not text:
        return saved["text"]
    database.set_summary(chat_id, text, len(old))
    return text
