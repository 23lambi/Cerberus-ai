# Per-model settings (Models → a model's Settings): how much of the chat the
# model sees at once (its context window), and how creative its answers are
# (temperature). Saved with the other settings, so backups and "Reset to
# defaults" include them. A model nobody set keeps the defaults.

import json

from cerberus.core.config import NUM_CTX
from cerberus.storage import database

KEY = "model_settings"
# Context windows to choose from, in tokens (about 3/4 of a word each).
CONTEXT_CHOICES = (4096, 8192, 16384, 32768, 65536, 131072)
SYSTEM_RESERVE_GB = 4  # left free for the system and other apps
# Ollama reserves a context's memory as soon as the model loads, even for a
# short chat. 32K already fits long chats and documents, so suggestions stop
# there; bigger windows stay a choice for people who need them.
SUGGEST_AT_MOST = 32768


def saved():
    try:
        data = json.loads(database.get_setting(KEY) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def get(model):
    """{"num_ctx": tokens, "temperature": 0..2, or None for the model's own}."""
    entry = saved().get(model) or {}
    num_ctx = entry.get("num_ctx")
    temperature = entry.get("temperature")
    if not (isinstance(temperature, (int, float)) and 0 <= temperature <= 2):
        temperature = None
    return {"num_ctx": num_ctx if num_ctx in CONTEXT_CHOICES else NUM_CTX, "temperature": temperature}


def num_ctx(model):
    return get(model)["num_ctx"]


def save(model, num_ctx, temperature):
    data = saved()
    entry = {}
    if num_ctx != NUM_CTX:
        entry["num_ctx"] = num_ctx
    if temperature is not None:
        entry["temperature"] = round(float(temperature), 2)
    if entry:
        data[model] = entry
    else:
        data.pop(model, None)  # back to the defaults: nothing to keep
    database.set_setting(KEY, json.dumps(data))


def context_gb(tokens, kv_bytes):
    """Memory a context window of this many tokens takes, in GB."""
    return tokens * kv_bytes / 1024**3


def suggest(ram_gb, model_gb, kv_bytes, longest):
    """The largest context window up to 32K that fits in memory beside the model."""
    choices = [c for c in CONTEXT_CHOICES if (not longest or c <= longest) and c <= SUGGEST_AT_MOST]
    if not (ram_gb and kv_bytes):
        return NUM_CTX if NUM_CTX in choices else choices[0]
    free = ram_gb - (model_gb or 0) - SYSTEM_RESERVE_GB
    fitting = [c for c in choices if context_gb(c, kv_bytes) <= free]
    return fitting[-1] if fitting else choices[0]
