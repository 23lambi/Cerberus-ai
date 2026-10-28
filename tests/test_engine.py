# Tests for getting Ollama (cerberus/engine.py) and the Setup checks
# (cerberus/setup.py). Nothing is downloaded or started for real: the
# archives are tiny ones made here, the download server is faked.

import asyncio
import io
import tarfile
import zipfile

import httpx
import pytest

from cerberus.engines import engine
from cerberus.core import setup


def make_tar_zst(path, files):
    """A .tar.zst like Ollama's Linux download: {name: bytes}."""
    with tarfile.open(path, mode="w:zst") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(data))


# ---------- Which download, for which computer ----------


@pytest.mark.parametrize("platform_name, machine, inside", [
    ("linux", "x86_64", "bin/ollama"),
    ("linux", "aarch64", "bin/ollama"),
    ("darwin", "arm64", "Ollama.app/Contents/Resources/ollama"),  # one zip for all Macs
    ("win32", "AMD64", "ollama.exe"),
])
def test_each_computer_gets_its_download(platform_name, machine, inside):
    url, found_inside = engine.download_for(platform_name, machine)
    assert url.startswith("https://ollama.com/download/") and found_inside == inside


def test_unknown_computers_get_no_download():
    assert engine.download_for("linux", "riscv64") is None


# ---------- Unpacking safely ----------


def test_unpack_a_tar_zst_and_find_the_program(tmp_path):
    archive = tmp_path / "ollama.tar.zst"
    make_tar_zst(archive, {"bin/ollama": b"#!/bin/sh\n", "lib/ollama/libggml.so": b"lib"})
    binary = engine.unpack(archive, tmp_path / "app", "bin/ollama")
    assert binary.read_bytes() == b"#!/bin/sh\n"
    assert binary.stat().st_mode & 0o100  # may run as a program


def test_a_tar_that_writes_outside_its_folder_is_refused(tmp_path):
    archive = tmp_path / "evil.tar.zst"
    make_tar_zst(archive, {"../../outside.txt": b"gotcha", "bin/ollama": b"x"})
    with pytest.raises(tarfile.TarError):
        engine.unpack(archive, tmp_path / "app", "bin/ollama")
    assert not (tmp_path.parent / "outside.txt").exists()


def test_a_zip_that_writes_outside_its_folder_is_refused(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("ollama.exe", b"x")
        zipped.writestr("../outside.txt", b"gotcha")
    with pytest.raises(engine.EngineError, match="outside its folder"):
        engine.unpack(archive, tmp_path / "app", "ollama.exe")
    assert not (tmp_path / "outside.txt").exists()


def test_a_zip_gets_its_program_runnable_again(tmp_path):
    # Zip files forget "may run as a program": unpack sets it again.
    archive = tmp_path / "ollama.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("Ollama.app/Contents/Resources/ollama", b"x")
    binary = engine.unpack(archive, tmp_path / "app", "Ollama.app/Contents/Resources/ollama")
    assert binary.stat().st_mode & 0o100


# ---------- Downloading, with resume ----------


def fake_server(monkeypatch, archive_bytes, cut_after=None):
    """A fake ollama.com. cut_after: the first answer stops after that many bytes."""
    requests = []

    def handler(request):
        requests.append(request.headers.get("range"))
        start = int(request.headers["range"].split("=")[1].rstrip("-")) if "range" in request.headers else 0
        body = archive_bytes[start:]
        if cut_after is not None and len(requests) == 1:
            body = body[:cut_after]
            return httpx.Response(200, content=body, headers={"content-length": str(len(archive_bytes))})
        return httpx.Response(206 if start else 200, content=body)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(engine.httpx, "AsyncClient",
                        lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(engine, "download_for", lambda: ("https://ollama.com/download/ollama.tar.zst", "bin/ollama"))
    return requests


async def collect(folder):
    return [step async for step in engine.download(folder)]


def test_download_unpacks_and_cleans_up(tmp_path, monkeypatch):
    archive = tmp_path / "source.tar.zst"
    make_tar_zst(archive, {"bin/ollama": b"program"})
    fake_server(monkeypatch, archive.read_bytes())
    folder = tmp_path / "ollama"

    steps = asyncio.run(collect(folder))

    assert steps[-1] == {"step": "done"} and {"step": "unpack"} in steps
    assert (folder / "app" / "bin" / "ollama").read_bytes() == b"program"
    assert sorted(p.name for p in folder.iterdir()) == ["app"]  # no leftover archive


def test_an_interrupted_download_continues_where_it_stopped(tmp_path, monkeypatch):
    archive = tmp_path / "source.tar.zst"
    make_tar_zst(archive, {"bin/ollama": b"program" * 1000})
    data = archive.read_bytes()
    folder = tmp_path / "ollama"
    folder.mkdir()
    # Half of it is already here, from a download that was cancelled.
    (folder / "ollama.tar.zst.part").write_bytes(data[: len(data) // 2])
    requests = fake_server(monkeypatch, data)

    asyncio.run(collect(folder))

    assert requests == [f"bytes={len(data) // 2}-"]  # only the missing half was asked for
    assert (folder / "app" / "bin" / "ollama").read_bytes() == b"program" * 1000


# ---------- Starting and stopping ----------


class FakeProcess:
    def __init__(self, args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


def test_start_runs_the_downloaded_ollama_only_here(tmp_path, monkeypatch):
    binary = tmp_path / "ollama"
    binary.write_text("x")
    started = []
    answers = iter([None, None, "0.40.6"])  # not running, still starting, running

    async def version():
        return next(answers)

    monkeypatch.setattr(engine, "version", version)
    monkeypatch.setattr(engine, "managed_binary", lambda: binary)
    monkeypatch.setattr(engine, "OLLAMA_DIR", tmp_path)
    monkeypatch.setattr(engine.subprocess, "Popen", lambda args, **kw: started.append(FakeProcess(args, **kw)) or started[-1])
    # No real waiting. The real sleep is kept first: engine.asyncio IS the
    # asyncio module, so a replacement calling asyncio.sleep would call itself.
    real_sleep = asyncio.sleep
    monkeypatch.setattr(engine.asyncio, "sleep", lambda seconds: real_sleep(0))

    asyncio.run(engine.start())

    assert started[0].args == [str(binary), "serve"]
    assert started[0].kwargs["env"]["OLLAMA_HOST"] == "127.0.0.1:11434"  # this computer only
    engine.stop()
    assert started[0].terminated and engine.process is None


def test_a_running_ollama_is_left_alone(monkeypatch):
    async def version():
        return "0.40.6"  # e.g. the system's Ollama

    monkeypatch.setattr(engine, "version", version)
    monkeypatch.setattr(engine.subprocess, "Popen", lambda *a, **k: pytest.fail("must not start a second one"))
    asyncio.run(engine.start())


def test_without_its_own_copy_cerberus_starts_nothing(monkeypatch):
    async def version():
        return None

    monkeypatch.setattr(engine, "version", version)
    monkeypatch.setattr(engine, "managed_binary", lambda: None)
    with pytest.raises(engine.EngineError, match="no Ollama of its own"):
        asyncio.run(engine.start())


# ---------- Setup checks ----------


@pytest.mark.parametrize("ram, model", [(4, "llama3.2:1b"), (12, "llama3.2:3b"), (32, "llama3.1:8b"), (None, "llama3.1:8b")])
def test_the_suggested_model_fits_the_memory(ram, model):
    assert setup.suggest_model(ram) == model


def test_searxng_settings_are_written_once_and_never_overwritten(tmp_path):
    first = setup.prepare_searxng(tmp_path)
    assert first["created"] and first["json_on"]
    text = (tmp_path / "settings.yml").read_text()
    assert "secret_key" in text and "{secret}" not in text
    assert "secret" not in str(first).replace("secret_key", "")  # the secret isn't sent to the page
    (tmp_path / "settings.yml").write_text("my own settings")
    again = setup.prepare_searxng(tmp_path)
    assert not again["created"] and not again["json_on"]
    assert (tmp_path / "settings.yml").read_text() == "my own settings"


@pytest.mark.parametrize("platform_name, sudo", [("linux", True), ("darwin", False), ("win32", False)])
def test_searxng_commands_per_system(platform_name, sudo):
    commands = setup.searxng_commands(platform_name)
    assert any("docker run" in c for c in commands)
    assert any(c.startswith("sudo") for c in commands) == sudo  # Docker Desktop needs no sudo


@pytest.mark.parametrize("answer, expected", [(200, "ok"), (403, "json_off"), (None, "offline")])
def test_searxng_check(monkeypatch, answer, expected):
    def handler(request):
        if answer is None:
            raise httpx.ConnectError("refused")
        return httpx.Response(answer, json={})

    monkeypatch.setattr(setup.websearch, "new_client",
                        lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert asyncio.run(setup.searxng_check("http://127.0.0.1:8888")) == expected
