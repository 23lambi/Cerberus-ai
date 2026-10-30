"""Settings → Help → Copy diagnostics."""
from types import SimpleNamespace

from cerberus.core import diagnostics


def test_home_folder_never_appears(tmp_path):
    assert diagnostics.without_home(f"log: {tmp_path}/app.log", home=tmp_path) == "log: ~/app.log"


def test_log_shows_only_its_end(tmp_path):
    (tmp_path / "app.log").write_text("\n".join(f"line {n}" for n in range(100)), encoding="utf-8")
    tail = diagnostics.log_tail(SimpleNamespace(root=tmp_path), lines=3)
    assert tail == "line 97\nline 98\nline 99"
    assert "source" in diagnostics.log_tail(None)


def test_report_lists_engine_and_model_without_keys(client, monkeypatch):
    async def status():
        return {"engine": {"kind": "openai", "name": "OpenRouter", "cloud": True, "running": False,
                           "error": "Wrong API key", "key_set": True},
                "ollama": {"running": True, "version": "0.40.6"}, "ram_gb": 16.0,
                "chat_models": [], "web": {"name": "SearXNG", "status": "offline"}}
    monkeypatch.setattr(diagnostics.setup, "status", status)
    text = client.get("/diagnostics", params={"model": "llama3.2:3b\nsneaky second line"}).text
    assert "Engine: OpenRouter (cloud), not connected" in text
    assert "Engine error: Wrong API key" in text
    assert "Chosen model: llama3.2:3b sneaky second line" in text  # one line, as typed
    assert "key_set" not in text and "Memory: 16.0 GB" in text
