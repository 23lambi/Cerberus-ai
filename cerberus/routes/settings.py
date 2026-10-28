# The Settings dialog: read, save and reset. Every route answers with all
# settings, so the page can show the values that were really saved.

from fastapi import APIRouter

from cerberus import prompts, settings

router = APIRouter(prefix="/settings")

# The built-in prompts, shown read-only in Settings, so you can see exactly
# what Cerberus tells the model. They live in cerberus/prompts.py; change
# them there. Each one: (name, what it's for, the text).
BUILT_IN = [
    ("Guard", "Sorts every message into normal chat or memory.", prompts.GUARD_PROMPT),
    ("Memory: saved", "When you say \"remember that...\".", prompts.KEEPER_SAVED),
    ("Memory: recall", "When memories or documents were found for a question.", prompts.KEEPER_RECALL),
    ("Memory: nothing found", "Stops the model from inventing memories.", prompts.KEEPER_NOTHING),
    ("Memory notes", "Put in front of your message with what was found.", prompts.CONTEXT_NOTE),
    ("Summary", "Rolls old messages of a long chat into a summary.", prompts.SUMMARY_PROMPT),
    ("Deep think 1: draft", "The first answer.", prompts.DEEP_THINK["draft"]),
    ("Deep think 2: review", "Checks the draft for mistakes.", prompts.DEEP_THINK["review"]),
    ("Deep think 3: final", "The answer you see, with the fixes.", prompts.DEEP_THINK["final"]),
    ("Project recap", "Notes about a project chat, for its other chats.", prompts.RECAP_PROMPT),
    ("Project notes", "How those notes are given to the model.", prompts.PROJECT_NOTES),
    ("Eyes", "Asks a vision model to describe your images.", prompts.EYES_PROMPT),
    ("Reverse: skill", "Added to the personality in the Reverse panel.", prompts.SKILLS["reverse"]),
    ("Reverse: facts", "How the facts about a file are given to the model.", prompts.REVERSE_FACTS),
    ("Tools", "Added when Tools is on: when to use which tool.", prompts.TOOLS_NOTE),
    ("Reverse: tools", "Added in the Reverse panel when Tools is on.", prompts.REVERSE_TOOLS_NOTE),
    ("Web", "Added when web pages were found for your message.", prompts.WEB_NOTE),
    ("Web: failed", "Added when the web search didn't work.", prompts.WEB_FAILED),
]


@router.get("")
def get_settings():
    return settings.get_all()


@router.get("/prompts")
def built_in_prompts():
    return {
        "prompts": [
            {"name": name, "about": about, "text": text.strip()}
            for name, about, text in BUILT_IN
        ]
    }


# dict[str, str]: the body must be a JSON object with text values.
@router.put("")
def update_settings(values: dict[str, str]):
    settings.update(values)
    return settings.get_all()


@router.post("/reset")
def reset_settings():
    settings.reset()
    return settings.get_all()
