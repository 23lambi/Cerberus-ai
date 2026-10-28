# Getting the AI engine (Ollama) ready, for the Setup window.
#
# Three situations:
#   1. Ollama is installed on the system (a package or installer) and runs:
#      Cerberus just uses it.
#   2. Installed but not running: Cerberus says how to start it. It doesn't
#      start a system Ollama itself: run as you instead of as its service,
#      it would look for models in another folder and "lose" yours.
#   3. Not installed: Cerberus downloads Ollama's official ready-to-run
#      version into its own folder (no admin rights needed), and starts and
#      stops that copy together with Cerberus.

import asyncio
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import httpx

from cerberus.config import OLLAMA_URL, system_data_dir

# Where the downloaded Ollama lives: the system's app folder, not your
# project or data folder. It's a program, and must never end up in git.
OLLAMA_DIR = system_data_dir() / "ollama"

# Ollama's official downloads, and where the program is inside each one.
DOWNLOADS = {
    ("linux", "x86_64"): ("https://ollama.com/download/ollama-linux-amd64.tar.zst", "bin/ollama"),
    ("linux", "aarch64"): ("https://ollama.com/download/ollama-linux-arm64.tar.zst", "bin/ollama"),
    ("darwin", "any"): ("https://ollama.com/download/Ollama-darwin.zip", "Ollama.app/Contents/Resources/ollama"),
    ("win32", "x86_64"): ("https://ollama.com/download/ollama-windows-amd64.zip", "ollama.exe"),
}

# How to start an Ollama that is installed but not running, per system.
START_HINTS = {
    "linux": "sudo systemctl start ollama   (or: ollama serve)",
    "darwin": "Open the Ollama app (in Applications).",
    "win32": "Start Ollama from the Start menu.",
}

# The Ollama that Cerberus started itself, so it can stop it again.
process = None


class EngineError(Exception):
    pass


def system_name(platform_name=sys.platform):
    return "linux" if platform_name.startswith("linux") else platform_name


def download_for(platform_name=sys.platform, machine=platform.machine()):
    """(url, the program's path inside) for this computer, or None."""
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(machine.lower(), machine.lower())
    system = system_name(platform_name)
    return DOWNLOADS.get((system, "any")) or DOWNLOADS.get((system, machine))


def managed_binary(folder=None):
    """The Ollama that Cerberus downloaded, or None."""
    found = download_for()
    if not found:
        return None
    binary = (folder or OLLAMA_DIR) / "app" / found[1]
    return binary if binary.is_file() else None


async def version():
    """Ollama's version when it answers, else None."""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(f"{OLLAMA_URL}/api/version")
        return response.json().get("version")
    except (httpx.HTTPError, ValueError):
        return None


async def status():
    running = await version()
    managed = managed_binary()
    system_binary = shutil.which("ollama")
    return {
        "running": running is not None,
        "version": running,
        # Where it comes from: Cerberus's own copy, or the system's.
        "managed": str(managed) if managed else None,
        "system": system_binary,
        "can_download": download_for() is not None,
        "start_hint": START_HINTS.get(system_name(), ""),
    }


# ---------- Downloading ----------


def unpack(archive, target, inside):
    """Unpack Ollama into target and return the program's path.

    Archives are checked first: a path like "../../.bashrc" inside could
    otherwise write files anywhere on the computer.
    """
    if str(archive).endswith(".zip"):
        with zipfile.ZipFile(archive) as zipped:
            for name in zipped.namelist():
                path = (target / name).resolve()
                if not path.is_relative_to(target.resolve()):
                    raise EngineError("The download contains a file outside its folder. It was not unpacked.")
            zipped.extractall(target)
    else:
        # filter="data" refuses paths outside target, links pointing out,
        # and device files: the safe way to unpack a .tar.
        with tarfile.open(archive, mode="r:zst") as tar:
            tar.extractall(target, filter="data")
    binary = target / inside
    if not binary.is_file():
        raise EngineError("The download didn't contain Ollama where expected.")
    # Zip files don't keep "may run as a program"; set it again.
    binary.chmod(binary.stat().st_mode | 0o755)
    return binary


async def download(folder=None):
    """Download and unpack Ollama, as a stream of steps for the page:
    {"step": "download", "completed": ..., "total": ...}, {"step": "unpack"},
    {"step": "done"}. An interrupted download continues where it stopped.
    """
    found = download_for()
    if not found:
        raise EngineError("There is no Ollama download for this kind of computer.")
    url, inside = found
    folder = folder or OLLAMA_DIR
    folder.mkdir(parents=True, exist_ok=True)
    part = folder / (url.rsplit("/", 1)[1] + ".part")

    # Resume: ask only for the bytes we don't have yet ("Range").
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=120), follow_redirects=True) as client:
            async with client.stream("GET", url, headers=headers) as response:
                if response.status_code == 416:  # we already have all of it
                    pass
                elif response.status_code not in (200, 206):
                    raise EngineError(f"ollama.com answered with error {response.status_code}.")
                else:
                    if response.status_code == 200:
                        have = 0  # the server sent everything again: start over
                    total = have + int(response.headers.get("content-length", 0))
                    with part.open("ab" if have else "wb") as file:
                        async for chunk in response.aiter_bytes(1024 * 1024):
                            file.write(chunk)
                            have += len(chunk)
                            yield {"step": "download", "completed": have, "total": total}
    except httpx.HTTPError:
        raise EngineError("The download stopped. Try again: it continues where it stopped.") from None

    yield {"step": "unpack"}
    target = folder / "app.new"
    shutil.rmtree(target, ignore_errors=True)
    archive = part.with_suffix("")  # without ".part": the finished file
    part.rename(archive)
    try:
        # Unpacking 1.4 GB takes a while; in a thread, so the server stays responsive.
        await asyncio.to_thread(unpack, archive, target, inside)
    except (tarfile.TarError, zipfile.BadZipFile, OSError) as error:
        shutil.rmtree(target, ignore_errors=True)
        raise EngineError(f"The download could not be unpacked: {error}") from None
    finally:
        archive.unlink(missing_ok=True)
    # Swap in the new copy only when it's complete.
    shutil.rmtree(folder / "app", ignore_errors=True)
    target.rename(folder / "app")
    yield {"step": "done"}


# ---------- Starting and stopping Cerberus's own Ollama ----------


async def start():
    """Start the downloaded Ollama, and wait until it answers."""
    global process
    if await version():
        return  # already running (maybe the system's): nothing to do
    binary = managed_binary()
    if binary is None:
        raise EngineError("Cerberus has no Ollama of its own to start.")
    log = (OLLAMA_DIR / "ollama.log").open("ab")
    # 127.0.0.1: only this computer can reach it, like Cerberus itself.
    env = {**os.environ, "OLLAMA_HOST": "127.0.0.1:11434"}
    # On Windows, no black console window next to the app.
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen([str(binary), "serve"], stdout=log, stderr=log, env=env, creationflags=flags)
    for _ in range(60):  # up to 15 seconds
        await asyncio.sleep(0.25)
        if await version():
            return
        if process.poll() is not None:
            break
    raise EngineError(f"Ollama didn't start. Its log is in {OLLAMA_DIR / 'ollama.log'}.")


def stop():
    """Stop the Ollama that Cerberus started (never a system Ollama)."""
    global process
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    process = None
