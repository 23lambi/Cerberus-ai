# "Copy diagnostics" in Settings → Help: the facts a bug report needs, as
# plain text. The user reads it before sharing it. It never contains chats or
# API keys, and the home folder becomes "~", so the user name stays out.

import platform
from pathlib import Path

from cerberus.core import setup, updates
from cerberus.core.version import VERSION

LOG_LINES = 40


def without_home(text, home=None):
    home = str(home or Path.home())
    return text.replace(home, "~") if len(home) > 1 else text


def log_tail(manager, lines=LOG_LINES):
    """The end of the app's log. Only the launcher-installed app writes one."""
    if manager is None:
        return "No log file: Cerberus runs from source, so messages go to its terminal."
    try:
        text = (manager.root / "app.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "No log file yet."
    return "\n".join(text.splitlines()[-lines:]) or "The log is empty."


async def report(model=""):
    state = await setup.status()
    manager = updates.installation()
    engine, ollama = state["engine"], state["ollama"]
    # The model comes from the page; keep it to one short line.
    model = " ".join(str(model).split())[:120] or "none chosen"
    name = engine.get("name", "Ollama") + (" (cloud)" if engine.get("cloud") else "")
    lines = [
        "Cerberus diagnostics",
        f"Version: {VERSION}, {'installed with the launcher' if manager else 'run from source'}",
        f"System: {platform.platform()} ({platform.machine()})",
        f"Python: {platform.python_version()}",
        f"Memory: {state['ram_gb']} GB" if state["ram_gb"] else "Memory: unknown",
        f"Engine: {name}, {'connected' if engine['running'] else 'not connected'}",
    ]
    if engine.get("error"):
        lines.append(f"Engine error: {engine['error']}")
    lines += [
        f"Ollama: {'version ' + ollama['version'] if ollama['running'] else 'not running'}",
        f"Chat models available: {len(state['chat_models'])}",
        f"Chosen model: {model}",
        f"Web search: {state['searxng']['status']}",
        "",
        f"Last {LOG_LINES} lines of the log:",
        log_tail(manager),
    ]
    return without_home("\n".join(lines))
