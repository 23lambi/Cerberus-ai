# API keys for cloud engines (Hugging Face, OpenAI, Groq...).
#
# A key is like a password: whoever has it can use your account. So keys
# are NOT stored in cerberus.db with the other settings. That file goes
# into every backup ZIP, and settings are sent to the browser. Keys live
# in their own small file, which only your user may read (chmod 600), in
# the system's app folder, and the browser only ever learns "a key is set".

import json
import os

from cerberus.core.config import system_data_dir

KEYS_FILE = system_data_dir() / "keys.json"


def load(path=None):
    path = path or KEYS_FILE
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def get(name, path=None):
    return load(path).get(name, "")


def set(name, value, path=None):
    """Save a key, or remove it with value "". Only this user can read the file."""
    path = path or KEYS_FILE
    keys = load(path)
    if not value and name not in keys:
        return  # nothing to remove: don't create a file for nothing
    if value:
        keys[name] = value
    else:
        keys.pop(name, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create the file with the right permissions from the start (0o600 =
    # read and write for you, nothing for anyone else), instead of fixing
    # them afterwards, when someone could already have read it.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as file:
        json.dump(keys, file)
    os.chmod(path, 0o600)  # also when the file already existed
