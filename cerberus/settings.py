from cerberus import database
from cerberus.prompts import HEADS, JUDGE_PROMPT, SYSTEM_PROMPT

DEFAULTS = {
    "system_prompt": SYSTEM_PROMPT.strip(),
    "thinker_prompt": HEADS["thinker"].strip(),
    "coder_prompt": HEADS["coder"].strip(),
    "critic_prompt": HEADS["critic"].strip(),
    "judge_prompt": JUDGE_PROMPT.strip(),
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
