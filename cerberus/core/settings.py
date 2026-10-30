# Settings the user can change in the Settings dialog. They are saved in
# the database; anything never saved falls back to DEFAULTS.

from cerberus.storage import database, keys
from cerberus.engines.ollama import OllamaError, list_models
from cerberus.chat.prompts import OLD_SYSTEM_PROMPTS, SKILLS, SYSTEM_PROMPT
from cerberus.core.config import WEB_ENGINES

# The API keys you can enter in Settings. They never go into the database.
KEYS = ("openai_key", "brave_key", "tavily_key")

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
    # Web search (see websearch.py): which engine, and where SearXNG is.
    # Brave and Tavily keys are kept with the other keys (keys.py).
    "web_engine": "searxng",
    "web_url": "http://127.0.0.1:8888",
    # SearXNG's switch: "yes" = it runs while Cerberus is open (searxng.py).
    "searxng_on": "yes",
    # The AI engine: "ollama", or "openai" for any OpenAI-compatible engine
    # (openai_api.py). openai_url "" = the preset's own address.
    "engine": "ollama",
    "openai_preset": "huggingface",
    "openai_url": "",
    "llamacpp_on": "no",
    "llamacpp_binary": "llama-server",
    "llamacpp_model": "",
    "llamacpp_port": "8080",
}


def get(key):
    # The saved value, or the default when the user never changed it.
    value = database.get_setting(key)
    if value is None:
        return DEFAULTS[key]
    if key == "system_prompt" and value.strip() in OLD_SYSTEM_PROMPTS:
        return DEFAULTS[key]  # an unchanged old default: use the new one
    return value


def get_all():
    # A dict comprehension: builds {"system_prompt": "...", ...} in one line.
    values = {key: get(key) for key in DEFAULTS}
    # A key itself never goes to the browser: only whether there is one.
    for name in KEYS:
        values[f"{name}_set"] = "yes" if keys.get(name) else "no"
    return values


def update(values):
    # A new API key goes to its own private file, never into the database
    # (see keys.py). An empty one means "keep the key I have".
    for name in KEYS:
        if values.get(name):
            keys.set(name, values[name].strip())
    for key, value in values.items():
        if key == "web_engine" and value not in WEB_ENGINES:
            continue  # an engine Cerberus doesn't know
        # Ignore unknown keys, so nobody can fill the table with junk.
        if key in DEFAULTS:
            # The unchanged personality is not stored, so it keeps following
            # the default when a new version improves it.
            if key == "system_prompt" and value.strip() in (DEFAULTS[key], *OLD_SYSTEM_PROMPTS):
                database.delete_setting(key)
            else:
                database.set_setting(key, value)


def reset():
    # Deleting the saved values makes get() fall back to the defaults. The
    # API keys go too: "reset everything" shouldn't leave a password behind.
    database.clear_settings()
    for name in KEYS:
        keys.set(name, "")


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
