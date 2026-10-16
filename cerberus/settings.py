from cerberus import database
from cerberus.prompts import SKILLS, SYSTEM_PROMPT

# Only the brain's personality can be edited. Skills are part of the features.
DEFAULTS = {
    "system_prompt": SYSTEM_PROMPT.strip(),
}


def get(key):
    value = database.get_setting(key)
    if value is None:
        return DEFAULTS[key]
    return value


def get_all():
    return {key: get(key) for key in DEFAULTS}


def update(values):
    for key, value in values.items():
        if key in DEFAULTS:
            database.set_setting(key, value)


def reset():
    database.clear_settings()


def brain(skill=None):
    """The one personality, plus a feature's skill when there is one."""
    prompt = get("system_prompt")
    if skill:
        prompt += "\n" + SKILLS[skill].strip()
    return prompt
