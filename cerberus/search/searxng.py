# SearXNG without Docker: Cerberus installs it with Python and starts and
# stops it together with itself, like its own Ollama (engine.py).
#
# SearXNG is not one program to download, like Ollama: it's a Python web
# app. So installing it means the same steps as SearXNG's own install
# script (utils/searxng.sh), done for you:
#   1. git clone: its code (it reads its version from git, so not a ZIP)
#   2. a venv of its own: its packages never mix with Cerberus's
#   3. pip install: its packages, as SearXNG's script installs them
#   4. settings.yml: JSON on, only this computer, a random secret
# Then "python -m searx.webapp" runs it on 127.0.0.1:8888.
#
# Everything lives in one folder in the system's app folder; removing that
# folder removes SearXNG completely. Works on Linux and macOS. On Windows
# SearXNG isn't officially supported: it may work, Docker is surer.

import asyncio
import os
import secrets
import shutil
import subprocess
import sys

from cerberus.core import settings
from cerberus.core.config import system_data_dir
from cerberus.search import websearch
from cerberus.search.websearch import searxng_check

HOME = system_data_dir() / "searxng"
REPOSITORY = "https://github.com/searxng/searxng.git"
PORT = 8888
URL = f"http://127.0.0.1:{PORT}"

# The same settings as for Docker (setup.py), plus where to listen:
# 127.0.0.1 means only this computer can reach it.
SETTINGS = """# SearXNG settings for Cerberus. Everything not listed here uses
# SearXNG's own defaults (use_default_settings).
use_default_settings: true

server:
  bind_address: "127.0.0.1"
  port: {port}
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

# SearXNG's install script installs these first; its own install needs them.
BUILD_PACKAGES = ["pip", "setuptools", "wheel", "pyyaml", "msgspec", "typing-extensions", "pybind11"]

# The SearXNG that Cerberus started itself, so it can stop it again.
process = None


class SearxngError(Exception):
    pass


def venv_python(home=None):
    """The Python inside SearXNG's own venv (Windows keeps it elsewhere)."""
    venv = (home or HOME) / "venv"
    return venv / "Scripts" / "python.exe" if sys.platform == "win32" else venv / "bin" / "python"


def installed(home=None):
    # The marker is written last, so a stopped install never counts.
    return ((home or HOME) / "installed").is_file()


def can_install():
    """"" when Cerberus can install SearXNG here, else why not."""
    if getattr(sys, "frozen", False):
        # A packaged Cerberus (PyInstaller) has no Python to make a venv with.
        return "The packaged app can't install SearXNG. Use Docker, or another search engine."
    if not shutil.which("git"):
        return "Installing SearXNG needs Git. Install it from https://git-scm.com, then try again."
    return ""


def write_settings(home=None):
    """settings.yml, once: an existing one may have your own changes."""
    path = (home or HOME) / "settings.yml"
    if not path.exists():
        # secrets: random numbers meant for passwords (random isn't).
        path.write_text(SETTINGS.format(port=PORT, secret=secrets.token_hex(32)))
    return path


def environment(home=None):
    # SEARXNG_SETTINGS_PATH: where SearXNG reads its settings.
    return {**os.environ, "SEARXNG_SETTINGS_PATH": str(write_settings(home))}


def no_window():
    # On Windows, no black console window next to the app.
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


async def run(command, log, cwd=None):
    """Run one install command, its output into the log. Raises on failure.

    Popen and a short sleep, instead of asyncio's own subprocesses: those
    don't work in every event loop on Windows. When you press Cancel, the
    page closes the connection, this coroutine is cancelled, and the
    finally below stops the command too.
    """
    log.write(f"\n$ {' '.join(map(str, command))}\n".encode())
    log.flush()
    child = subprocess.Popen([str(part) for part in command], stdout=log, stderr=subprocess.STDOUT,
                             cwd=cwd, creationflags=no_window())
    try:
        while child.poll() is None:
            await asyncio.sleep(0.3)
    finally:
        if child.poll() is None:
            child.kill()
    if child.returncode != 0:
        raise SearxngError(f"This step failed. The details are in {log.name}.")


async def install(home=None):
    """Install SearXNG, as a stream of steps for the page:
    {"step": "download"}, {"step": "venv"}, {"step": "packages"}, {"step": "done"}.
    """
    home = home or HOME
    problem = can_install()
    if problem:
        raise SearxngError(problem)
    home.mkdir(parents=True, exist_ok=True)
    (home / "installed").unlink(missing_ok=True)
    source = home / "src"
    with (home / "install.log").open("ab") as log:
        yield {"step": "download"}
        if (source / ".git").is_dir():
            await run(["git", "-C", source, "pull", "--ff-only"], log)  # installed before: update
        else:
            shutil.rmtree(source, ignore_errors=True)  # a half-finished clone
            # --depth 1: only the newest version, not years of history.
            await run(["git", "clone", "--depth", "1", REPOSITORY, source], log)

        yield {"step": "venv"}
        python = venv_python(home)
        if not python.is_file():
            # sys.executable: the Python running Cerberus makes the venv.
            await run([sys.executable, "-m", "venv", home / "venv"], log)

        yield {"step": "packages"}
        await run([python, "-m", "pip", "install", "-U", *BUILD_PACKAGES], log)
        # -e: SearXNG runs from src, so "git pull" later updates it.
        await run([python, "-m", "pip", "install", "--use-pep517", "--no-build-isolation", "-e", source],
                  log, cwd=source)

    write_settings(home)
    (home / "installed").write_text("yes")
    yield {"step": "done"}


async def start(home=None):
    """Start the installed SearXNG and wait until it answers."""
    global process
    home = home or HOME
    if await searxng_check(URL) == "ok":
        return  # already running (maybe yours, in Docker): nothing to do
    if not installed(home):
        raise SearxngError("Cerberus has no SearXNG of its own to start.")
    log = (home / "searxng.log").open("ab")
    process = subprocess.Popen([str(venv_python(home)), "-m", "searx.webapp"], cwd=home / "src",
                               stdout=log, stderr=subprocess.STDOUT, env=environment(home),
                               creationflags=no_window())
    for _ in range(120):  # up to 30 seconds: the first start is slow
        await asyncio.sleep(0.25)
        if await searxng_check(URL) == "ok":
            return
        if process.poll() is not None:
            break
    stop()
    raise SearxngError(f"SearXNG didn't start. Its log is in {home / 'searxng.log'}.")


def stop():
    """Stop the SearXNG that Cerberus started (never yours in Docker)."""
    global process
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    process = None


# ---------- SearXNG in Docker ----------
#
# A SearXNG made with the Docker commands from Setup is a container named
# "searxng". Cerberus can start and stop it with the docker command, but
# only where that works without sudo: Docker Desktop (Windows, macOS), or
# Linux when you are in the "docker" group. Otherwise Docker would need
# your password, so Cerberus shows the command instead.

CONTAINER = "searxng"


def run_docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=30,
                          creationflags=no_window())


def docker_state():
    """"running", "stopped", "missing" (no container named searxng),
    "no_permission" (Docker needs sudo here), or "no_docker"."""
    if not shutil.which("docker"):
        return "no_docker"
    try:
        # inspect: facts about the container; .State.Running is true or false.
        done = run_docker("inspect", "--format", "{{.State.Running}}", CONTAINER)
    except (OSError, subprocess.TimeoutExpired):
        return "no_docker"
    if done.returncode == 0:
        return "running" if done.stdout.strip() == "true" else "stopped"
    error = done.stderr.lower()
    if "permission denied" in error:
        return "no_permission"
    if "no such" in error:
        return "missing"
    return "no_docker"  # Docker itself isn't running (Docker Desktop closed)


def switch_docker(on):
    """Start or stop the Docker SearXNG. Returns "" when done, or the
    command to run yourself when Docker needs sudo here."""
    state = docker_state()
    if state == "no_permission":
        return websearch.docker(("start " if on else "stop ") + CONTAINER)
    if state == ("stopped" if on else "running"):
        # -t 5: give it 5 seconds to finish, not Docker's usual 10.
        done = run_docker("start", CONTAINER) if on else run_docker("stop", "-t", "5", CONTAINER)
        if done.returncode != 0:
            raise SearxngError("Docker couldn't " + ("start" if on else "stop") + " SearXNG: " + done.stderr.strip())
    return ""


# ---------- The on/off switch ----------
#
# On (the default): SearXNG runs while Cerberus is open, and stops when you
# close Cerberus. Off: it's stopped, and Cerberus doesn't start it.


def is_on():
    return settings.get("searxng_on") != "no"


def used():
    # Web search uses SearXNG at the address Cerberus's own one has (where
    # the Docker one listens too, with the commands from Setup).
    return settings.get("web_engine") == "searxng" and settings.get("web_url") == URL


async def switch(on):
    """The switch in Settings and Setup: save it, then start or stop SearXNG
    now. Returns "" or a command you must run yourself (see switch_docker)."""
    settings.update({"searxng_on": "yes" if on else "no"})
    if installed() and on:
        await start()
        return ""
    if not on and process is not None and process.poll() is None:
        stop()  # Cerberus's own was the one running: that's all
        return ""
    # In a thread: docker can take a few seconds, the app must not freeze.
    return await asyncio.to_thread(switch_docker, on)


async def start_saved():
    """At Cerberus's start: start SearXNG when it's on and web search uses it."""
    if not (is_on() and used()):
        return
    if installed():
        await start()
    else:
        await asyncio.to_thread(switch_docker, True)


def stop_saved():
    """When Cerberus closes: SearXNG stops too, when it's on and used."""
    stop()
    if is_on() and used() and not installed():
        try:
            switch_docker(False)
        except SearxngError as error:
            print("Cerberus:", error)


def remove(home=None):
    """Stop and delete Cerberus's SearXNG: code, venv, settings and logs."""
    stop()
    shutil.rmtree(home or HOME, ignore_errors=True)
