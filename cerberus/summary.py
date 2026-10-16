from cerberus import database
from cerberus.config import SUMMARY_EVERY
from cerberus.ollama import OllamaError, stream_chat
from cerberus.prompts import SUMMARY_PROMPT


def as_text(messages):
    lines = []
    for message in messages:
        who = "User" if message["role"] == "user" else "Cerberus"
        lines.append(f"{who}: {message['content'][:600]}")
    return "\n".join(lines)


async def old_part(chat_id, old, model):
    """Return a summary of the messages that no longer fit, updating it when needed."""
    if not chat_id or not old:
        return ""

    saved = database.get_summary(chat_id)
    if saved is None or saved["covered"] > len(old):
        saved = {"text": "", "covered": 0}

    new = old[saved["covered"]:]
    # Only redo the summary once enough new messages have fallen out.
    if saved["text"] and len(new) < SUMMARY_EVERY:
        return saved["text"]

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
