# The Setup window's checks: is everything Cerberus needs ready? The AI
# engine (engine.py), the models, and web search (SearXNG).

import ctypes
import os
import secrets
import sys
from pathlib import Path

from cerberus.engines import engine, ollama, openai_api
from cerberus.core import settings
from cerberus.search import searxng, websearch
from cerberus.search.websearch import searxng_check
from cerberus.core.config import EMBED_MODEL, WEB_ENGINES
from cerberus.storage import keys

SEARXNG_DIR = Path.home() / "searxng"

# SearXNG's settings, as in README.md: JSON on (Cerberus reads JSON), the
# bot limiter off (it only answers you). The secret is filled in once.
SEARXNG_SETTINGS = """# SearXNG settings for Cerberus. Everything not listed here uses
# SearXNG's own defaults (use_default_settings).
use_default_settings: true

server:
  # A random password SearXNG uses to sign things. Never share it.
  secret_key: "{secret}"
  # The limiter protects public servers from bots. This one only
  # answers you, on this computer, so it isn't needed.
  limiter: false
  image_proxy: false

search:
  # html = the normal web page; json = what Cerberus reads.
  formats:
    - html
    - json
"""


def total_ram_gb():
    """The computer's memory in GB, or None when it can't be found out."""
    try:
        if sys.platform == "win32":
            # Windows: ask the system with GlobalMemoryStatusEx.
            class Memory(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            ("total", ctypes.c_ulonglong), ("available", ctypes.c_ulonglong),
                            ("page_total", ctypes.c_ulonglong), ("page_free", ctypes.c_ulonglong),
                            ("virtual_total", ctypes.c_ulonglong), ("virtual_free", ctypes.c_ulonglong),
                            ("extended", ctypes.c_ulonglong)]
            memory = Memory()
            memory.length = ctypes.sizeof(Memory)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory))
            return memory.total / 1024**3
        # Linux and macOS: page size times number of pages.
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except (AttributeError, OSError, ValueError):
        return None


def suggest_model(ram_gb):
    """A good first chat model for this much memory (on a CPU, smaller is faster)."""
    if ram_gb is not None and ram_gb < 8:
        return "llama3.2:1b"  # about 1.3 GB
    if ram_gb is not None and ram_gb < 16:
        return "llama3.2:3b"  # about 2 GB
    return "llama3.1:8b"  # about 5 GB, and it can use tools


def searxng_commands(platform_name=sys.platform):
    """The commands that start SearXNG in Docker, for this system."""
    run = ("docker run -d --name searxng --restart unless-stopped "
           "-p 127.0.0.1:8888:8080 -v {folder}:/etc/searxng docker.io/searxng/searxng:latest")
    if platform_name == "win32":
        # Docker Desktop needs no sudo; PowerShell writes the folder like this.
        return [run.format(folder='"${HOME}\\searxng"')]
    if platform_name == "darwin":
        return [run.format(folder="~/searxng")]
    return ["sudo systemctl enable --now docker", "sudo " + run.format(folder="~/searxng")]


def prepare_searxng(folder=SEARXNG_DIR):
    """Write SearXNG's settings file, once. Returns what's there now.

    An existing file is never overwritten: it may have your own changes.
    """
    path = folder / "settings.yml"
    created = False
    if not path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        # secrets: random numbers meant for passwords (random isn't).
        path.write_text(SEARXNG_SETTINGS.format(secret=secrets.token_hex(32)))
        created = True
    # A rough check: is "- json" among the formats?
    json_on = "- json" in path.read_text(errors="replace")
    return {"path": str(path), "created": created, "json_on": json_on, "commands": searxng_commands()}


async def web_status():
    """The chosen search engine and whether it can search, for the Setup window.

    "ok" (SearXNG answers), "json_off", "offline", "no_key", or "ready":
    DuckDuckGo, or an engine with its key. Those are not tried here: every
    try is a real search, and the APIs count them. "Save & test" tries.
    """
    engine = settings.get("web_engine")
    url = settings.get("web_url")
    if engine == "searxng" and not searxng.is_on():
        status = "off"
    elif engine == "searxng":
        status = await searxng_check(url)
    elif engine == "duckduckgo" or keys.get(f"{engine}_key"):
        status = "ready"
    else:
        status = "no_key"
    return {
        "web_engine": engine, "name": WEB_ENGINES[engine], "web_url": url, "status": status,
        # As in Settings: only whether a key is saved, never the key.
        **{f"{name}_set": "yes" if keys.get(name) else "no" for name in ("brave_key", "tavily_key")},
        "restart_command": websearch.docker("restart searxng"),
        # Cerberus's own SearXNG (searxng.py): installed? if not, can it be?
        "searxng_installed": searxng.installed(),
        "searxng_problem": searxng.can_install(),
        "searxng_windows": sys.platform == "win32",
        "searxng_on": "yes" if searxng.is_on() else "no",
    }


async def other_engine_status():
    """The chosen OpenAI-compatible engine: reachable? how many models?"""
    chosen = openai_api.current()
    state = {"kind": "openai", "name": chosen["name"], "preset": chosen["preset"], "url": chosen["url"],
             "cloud": chosen["cloud"], "key_set": bool(chosen["key"]), "running": False, "error": "", "models": []}
    try:
        state["models"] = await openai_api.list_models(chosen)
        state["running"] = True
    except openai_api.EngineError as error:
        state["error"] = str(error)
    return state


async def status():
    """Everything the Setup window shows."""
    ram = total_ram_gb()
    other = await other_engine_status() if ollama.engine() == "openai" else None
    ollama_state = await engine.status()
    state = {
        "engine": other or {"kind": "ollama", **ollama_state},
        # Ollama is still used for search by meaning (embeddings), whatever the engine.
        "ollama": ollama_state,
        "ram_gb": round(ram, 1) if ram else None,
        "suggested_model": suggest_model(ram),
        "embed_model": EMBED_MODEL,
        "embed_installed": False,
        "chat_models": [],
        "web": await web_status(),
    }
    if ollama_state["running"]:
        names = [m["name"] for m in await ollama.installed()]
        state["embed_installed"] = any(n.split(":")[0] == EMBED_MODEL for n in names)
        if not other:
            state["chat_models"] = [n for n in names if await ollama.can_chat(n)]
    if other:
        state["chat_models"] = other["models"]
    # Something important missing: the Setup window opens by itself.
    state["needs_setup"] = not state["engine"]["running"] or not state["chat_models"]
    return state
