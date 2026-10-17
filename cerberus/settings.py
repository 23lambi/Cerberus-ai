# Settings the user can change in the Settings dialog. They are saved in
# the database; anything never saved falls back to DEFAULTS.

from cerberus import database
from cerberus.ollama import OllamaError, list_models
from cerberus.prompts import SKILLS, SYSTEM_PROMPT

# Only the brain's personality can be edited. Skills are part of the features.
DEFAULTS = {
    "system_prompt": SYSTEM_PROMPT.strip(),
    # The Helper feature: a second model for the small background jobs
    # (the Guard, chat titles, summaries and project recaps). Settings are
    # saved as text, so on/off is "yes"/"no". Switching it off keeps the
    # chosen model, so switching it on again needs no new choice.
    "helper_on": "no",
    "helper_model": "",
    # The Eyes feature: a vision model that describes images for a chat
    # model that can't see them.
    "eyes_on": "no",
    "eyes_model": "",
}


def get(key):
    # The saved value, or the default when the user never changed it.
    value = database.get_setting(key)
    if value is None:
        return DEFAULTS[key]
    return value


def get_all():
    # A dict comprehension: builds {"system_prompt": "...", ...} in one line.
    return {key: get(key) for key in DEFAULTS}


def update(values):
    for key, value in values.items():
        # Ignore unknown keys, so nobody can fill the table with junk.
        if key in DEFAULTS:
            database.set_setting(key, value)


def reset():
    # Deleting the saved values makes get() fall back to the defaults.
    database.clear_settings()


def brain(skill=None):
    """The one personality, plus a feature's skill when there is one."""
    prompt = get("system_prompt")
    if skill:
        prompt += "\n" + SKILLS[skill].strip()
    return prompt


async def feature_model(feature):
    """The model of an on/off feature ("helper" or "eyes"), or None.

    Each feature has two settings: "<feature>_on" and "<feature>_model".
    None means: the feature is off, no model is picked, or the model was
    removed with "ollama rm" since it was chosen.
    """
    model = get(f"{feature}_model")
    if get(f"{feature}_on") != "yes" or not model:
        return None
    try:
        installed = await list_models()
    except OllamaError:
        return None
    return model if model in installed else None


async def helper_model():
    """The Helper's model when the Helper is on, otherwise None.

    The chef (chat model) writes the answers; the Helper does the small
    jobs around them, so a slow thinking model never has to make titles.
    """
    return await feature_model("helper")


async def eyes_model():
    """The Eyes' vision model when Eyes is on, otherwise None."""
    return await feature_model("eyes")


async def jobs_model(chat_model):
    """Who does a background job: the Helper when it's on, else the chat model."""
    # "a or b" = a, unless a is empty or None; then b.
    return await helper_model() or chat_model
