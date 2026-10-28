"""Start only the llama.cpp server Cerberus owns, bound to loopback."""

import asyncio
import os
import shutil
import socket
import subprocess
from pathlib import Path

import httpx

from cerberus.core import settings
from cerberus.core.config import system_data_dir

process = None
lock = asyncio.Lock()
START_TIMEOUT = 120


class EngineError(Exception):
    pass


def configuration():
    return {"binary": settings.get("llamacpp_binary"), "model": settings.get("llamacpp_model"),
            "port": settings.get("llamacpp_port"), "enabled": settings.get("llamacpp_on") == "yes",
            "owned": process is not None and process.poll() is None}


def selected():
    return (settings.get("engine") == "openai" and settings.get("openai_preset") == "llamacpp"
            and settings.get("llamacpp_on") == "yes")


def stop():
    global process
    if process is not None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        process = None


async def ready(port):
    try:
        async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
            response = await client.get(f"http://127.0.0.1:{port}/health")
        return response.status_code == 200
    except httpx.HTTPError:
        return False


async def start(binary, model, port):
    """Validate before spawning; on failure or cancellation reap our child."""
    global process
    async with lock:
        if process is not None and process.poll() is None:
            raise EngineError("Cerberus already has a llama.cpp server. Stop it before changing its settings.")
        executable = shutil.which(str(Path(binary.strip()).expanduser()))
        if not executable:
            raise EngineError("llama-server was not found. Install it or enter its executable path.")
        model_path = Path(model).expanduser().resolve()
        if not model.strip() or not model_path.is_file() or model_path.suffix.lower() != ".gguf":
            raise EngineError("Choose an existing GGUF model file on this computer.")
        if not 1 <= port <= 65535:
            raise EngineError("Choose a port between 1 and 65535.")
        # Never adopt or stop a server someone else started.
        try:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
        except OSError:
            raise EngineError("That port is already in use. Choose another port or connect to the existing server.") from None
        log_path = system_data_dir() / "llamacpp.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("ab") as log:
                # No shell; paths containing spaces remain single arguments.
                # Explicit flags override inherited llama.cpp configuration.
                env = {k: v for k, v in os.environ.items() if not k.startswith("LLAMA_ARG_")}
                process = subprocess.Popen(
                    [executable, "-m", str(model_path), "--host", "127.0.0.1", "--port", str(port),
                     "--jinja", "--ctx-size", "8192"],
                    stdout=log, stderr=log, env=env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            deadline = asyncio.get_running_loop().time() + START_TIMEOUT
            while asyncio.get_running_loop().time() < deadline:
                if process.poll() is not None:
                    break
                if await ready(port) and process.poll() is None:
                    return
                await asyncio.sleep(0.25)
            raise EngineError(f"llama.cpp did not become ready. See {log_path}.")
        except OSError as error:
            await asyncio.to_thread(stop)
            raise EngineError(f"Could not start llama.cpp: {error}") from None
        except BaseException:
            await asyncio.to_thread(stop)
            raise


async def start_saved():
    if selected():
        if process is not None and process.poll() is None:
            return
        try:
            port = int(settings.get("llamacpp_port"))
        except ValueError:
            raise EngineError("Invalid saved llama.cpp port.") from None
        await start(settings.get("llamacpp_binary"), settings.get("llamacpp_model"), port)
