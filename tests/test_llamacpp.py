import asyncio
import subprocess

import pytest

from cerberus import llamacpp, settings


class Child:
    def __init__(self, exited=False):
        self.exited = exited
        self.killed = False
        self.terminated = False

    def poll(self):
        return 1 if self.exited else None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        self.exited = True

    def wait(self, timeout=None):
        if timeout and not self.exited:
            raise subprocess.TimeoutExpired("llama-server", timeout)
        return 0


@pytest.fixture
def launch(tmp_path, monkeypatch):
    model = tmp_path / "a model.gguf"
    model.write_bytes(b"GGUF")
    monkeypatch.setattr(llamacpp, "process", None)
    monkeypatch.setattr(llamacpp, "lock", asyncio.Lock())
    monkeypatch.setattr(llamacpp, "system_data_dir", lambda: tmp_path)
    monkeypatch.setattr(llamacpp.shutil, "which", lambda binary: "/bin/llama-server")
    # The OS chooses a currently free port for each test.
    with llamacpp.socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return str(model), port


def test_launch_arguments_and_owned_shutdown(launch, monkeypatch):
    model, port = launch
    calls = []
    child = Child()
    monkeypatch.setattr(llamacpp.subprocess, "Popen", lambda *a, **kw: calls.append((a, kw)) or child)
    async def ready(port):
        return True
    monkeypatch.setattr(llamacpp, "ready", ready)
    monkeypatch.setenv("LLAMA_ARG_HOST", "0.0.0.0")
    asyncio.run(llamacpp.start("llama-server", model, port))
    args, kwargs = calls[0]
    assert args[0] == ["/bin/llama-server", "-m", model, "--host", "127.0.0.1", "--port", str(port),
                       "--jinja", "--ctx-size", "8192"]
    assert "LLAMA_ARG_HOST" not in kwargs["env"]
    assert not kwargs.get("shell")
    assert kwargs["stdout"].closed
    llamacpp.stop()
    assert child.terminated and child.killed and llamacpp.process is None


def test_failed_child_is_reaped(launch, monkeypatch):
    model, port = launch
    monkeypatch.setattr(llamacpp.subprocess, "Popen", lambda *a, **kw: Child(exited=True))
    with pytest.raises(llamacpp.EngineError, match="did not become ready"):
        asyncio.run(llamacpp.start("llama-server", model, port))
    assert llamacpp.process is None


def test_timeout_and_cancellation_reap_child(launch, monkeypatch):
    model, port = launch
    child = Child()
    monkeypatch.setattr(llamacpp.subprocess, "Popen", lambda *a, **kw: child)
    monkeypatch.setattr(llamacpp, "START_TIMEOUT", 0)
    with pytest.raises(llamacpp.EngineError):
        asyncio.run(llamacpp.start("llama-server", model, port))
    assert child.killed and llamacpp.process is None
    monkeypatch.setattr(llamacpp, "START_TIMEOUT", 120)
    monkeypatch.setattr(llamacpp.subprocess, "Popen", lambda *a, **kw: Child())
    async def cancelled(port):
        raise asyncio.CancelledError()
    monkeypatch.setattr(llamacpp, "ready", cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(llamacpp.start("llama-server", model, port))
    assert llamacpp.process is None


def test_port_in_use_is_never_adopted(launch, monkeypatch):
    model, _ = launch
    monkeypatch.setattr(llamacpp.subprocess, "Popen", lambda *a, **kw: pytest.fail("must not spawn"))
    with llamacpp.socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        with pytest.raises(llamacpp.EngineError, match="already in use"):
            asyncio.run(llamacpp.start("llama-server", model, sock.getsockname()[1]))
    assert llamacpp.process is None


def test_invalid_model_or_binary_never_spawns(launch, monkeypatch):
    _, port = launch
    monkeypatch.setattr(llamacpp.subprocess, "Popen", lambda *a, **kw: pytest.fail("must not spawn"))
    with pytest.raises(llamacpp.EngineError, match="GGUF"):
        asyncio.run(llamacpp.start("llama-server", "/missing.gguf", port))
    monkeypatch.setattr(llamacpp.shutil, "which", lambda binary: None)
    with pytest.raises(llamacpp.EngineError, match="not found"):
        asyncio.run(llamacpp.start("missing", "/missing.gguf", port))


def test_routes_save_only_success_and_disable(client, monkeypatch):
    calls = []
    async def start(*args):
        calls.append(args)
    monkeypatch.setattr(llamacpp, "start", start)
    response = client.post("/setup/llamacpp/start", json={"model": "/a.gguf", "port": 8123})
    assert response.status_code == 200
    assert calls == [("llama-server", "/a.gguf", 8123)]
    assert settings.get("openai_url") == "http://127.0.0.1:8123/v1"
    assert llamacpp.selected()
    assert client.get("/setup/engines").json()["llamacpp"]["enabled"]
    assert client.post("/setup/llamacpp/stop").status_code == 200
    assert not llamacpp.selected()
    async def fail(*args):
        raise llamacpp.EngineError("bad model")
    monkeypatch.setattr(llamacpp, "start", fail)
    assert client.post("/setup/llamacpp/start", json={"model": "/bad.gguf"}).status_code == 409
    assert settings.get("llamacpp_on") == "no"
    assert settings.get("llamacpp_model") == "/a.gguf"
    assert client.post("/setup/llamacpp/start", json={"model": "/a.gguf", "port": 70000}).status_code == 422


def test_auto_start_only_when_selected(db, monkeypatch):
    calls = []
    async def start(*args):
        calls.append(args)
    monkeypatch.setattr(llamacpp, "start", start)
    settings.update({"llamacpp_on": "yes", "llamacpp_model": "/a.gguf"})
    asyncio.run(llamacpp.start_saved())
    assert not calls
    settings.update({"engine": "openai", "openai_preset": "llamacpp"})
    asyncio.run(llamacpp.start_saved())
    assert calls == [("llama-server", "/a.gguf", 8080)]


def test_duplicate_start_is_refused(launch, monkeypatch):
    model, port = launch
    monkeypatch.setattr(llamacpp, "process", Child())
    with pytest.raises(llamacpp.EngineError, match="already has"):
        asyncio.run(llamacpp.start("llama-server", model, port))


def test_real_child_health_and_shutdown(tmp_path, monkeypatch):
    """Exercise subprocess ownership and HTTP readiness without loading an LLM."""
    import os
    import sys
    if os.name == "nt":
        pytest.skip("The temporary executable uses a POSIX shebang")
    server = tmp_path / "fake-llama-server"
    server.write_text(f"#!{sys.executable}\n" + '''
import http.server
import sys
port = int(sys.argv[sys.argv.index('--port') + 1])
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')
http.server.HTTPServer(('127.0.0.1', port), Handler).serve_forever()
''')
    server.chmod(0o700)
    model = tmp_path / "test.gguf"
    model.write_bytes(b"GGUF")
    monkeypatch.setattr(llamacpp, "process", None)
    monkeypatch.setattr(llamacpp, "lock", asyncio.Lock())
    monkeypatch.setattr(llamacpp, "system_data_dir", lambda: tmp_path)
    with llamacpp.socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    try:
        asyncio.run(llamacpp.start(str(server), str(model), port))
        child = llamacpp.process
        assert child.poll() is None
        assert asyncio.run(llamacpp.ready(port))
    finally:
        llamacpp.stop()
    assert child.poll() is not None
    assert not asyncio.run(llamacpp.ready(port))
