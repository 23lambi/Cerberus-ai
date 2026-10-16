# Projects: when you leave a chat inside a project, the model writes a
# short recap of it. Every other chat in the same project then gets these
# recaps in its system prompt, so the project "remembers" its own work.

from cerberus import database
from cerberus.config import PROJECT_NOTES_MAX_CHARS
from cerberus.ollama import OllamaError, stream_chat
from cerberus.prompts import PROJECT_NOTES, RECAP_PROMPT

MESSAGE_CHARS = 1500  # one long message is cut here
CHAT_CHARS = 12000  # about 3000 tokens, so prompt and recap fit in NUM_CTX 8192
RECAP_MAX_TOKENS = 250


def as_text(chat_id, messages):
    """The chat as plain text: the summary of the early part, then the newest messages."""
    saved = database.get_summary(chat_id)
    start = 0
    if saved and saved["covered"] <= len(messages):
        start = saved["covered"]  # these messages are already in the summary

    # Walk backwards from the newest message, so the end of the chat always fits.
    lines = []
    used = 0
    for message in reversed(messages[start:]):
        who = "User" if message["role"] == "user" else "Cerberus"
        line = f"{who}: {message['content'][:MESSAGE_CHARS]}"
        if used + len(line) > CHAT_CHARS:
            break
        lines.append(line)
        used += len(line)
    lines.reverse()  # back to oldest-first, the order a person reads in

    text = "\n".join(lines)
    if start:
        text = f"Summary of the early part:\n{saved['text']}\n\nThe rest:\n{text}"
    return text


async def make_recap(chat_id, model):
    """Write or refresh the recap of a project chat. Returns None when there's nothing to do."""
    chat = database.get_chat(chat_id)
    if chat is None or chat["project_id"] is None:
        return None  # only chats inside a project get recaps

    count = len(chat["messages"])
    if count < 2:
        return None  # not even one question and answer yet

    old = database.get_recap(chat_id)
    if old and old["message_count"] == count:
        return None  # nothing new since the last recap

    prompt = RECAP_PROMPT.format(chat=as_text(chat_id, chat["messages"]))
    text = ""
    try:
        async for piece in stream_chat(
            model,
            [{"role": "user", "content": prompt}],
            max_tokens=RECAP_MAX_TOKENS,
            temperature=0.2,  # low, so it sticks to what was said
        ):
            text += piece
    except OllamaError:
        return None  # keep the old recap rather than fail

    text = text.strip()
    if not text:
        return None
    database.set_recap(chat["project_id"], chat_id, text, count)
    return text


def notes_for(project_id, exclude_chat_id=None):
    """The project's notes as one text, newest first, up to PROJECT_NOTES_MAX_CHARS."""
    parts = []
    used = 0
    for note in database.project_notes(project_id, exclude_chat_id):
        # Notes from a chat are labelled with its title, others with their kind.
        label = note["title"] or note["kind"]
        part = f"[{label}, {note['updated_at'][:10]}] {note['text']}"
        if used + len(part) > PROJECT_NOTES_MAX_CHARS:
            break  # the older notes don't fit anymore
        parts.append(part)
        used += len(part)
    return "\n\n".join(parts)


def project_prompt(chat_id):
    """The project notes for the system prompt, or "" when this chat isn't in a project."""
    if not chat_id:
        return ""
    chat = database.get_chat(chat_id)
    if chat is None or chat["project_id"] is None:
        return ""
    project = database.get_project(chat["project_id"])
    # Leave out this chat's own recap: the model already sees the chat itself.
    notes = notes_for(chat["project_id"], exclude_chat_id=chat_id)
    if project is None or not notes:
        return ""
    return PROJECT_NOTES.format(name=project["name"], notes=notes)
