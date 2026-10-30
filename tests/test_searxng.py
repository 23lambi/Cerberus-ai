# Tests for Cerberus's own SearXNG (cerberus/search/searxng.py). git, pip
# and SearXNG itself are faked: we check which commands Cerberus runs, in
# which order, and what it does when one fails. No internet needed.

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from cerberus.core import settings
from cerberus.search import searxng


@pytest.fixture
def home(tmp_path):
    return tmp_path / "searxng"


@pytest.fixture
def commands(monkeypatch):
    """Every command install() runs, instead of running it."""
    ran = []

    async def run(command, log, cwd=None):
        ran.append([str(part) for part in command])
        if command[:2] == ["git", "clone"]:
            Path(command[-1], ".git").mkdir(parents=True)  # as if cloned
        if command[1:3] == ["-m", "venv"]:
            python = searxng.venv_python(Path(command[-1]).parent)
            python.parent.mkdir(parents=True)
            python.write_text("")

    monkeypatch.setattr(searxng, "run", run)
    monkeypatch.setattr(searxng.shutil, "which", lambda name: "/usr/bin/" + name)
    return ran


def install(home):
    async def steps():
        return [step async for step in searxng.install(home)]
    return asyncio.run(steps())


def test_install_follows_searxngs_own_steps(home, commands):
    steps = install(home)

    assert [s["step"] for s in steps] == ["download", "venv", "packages", "done"]
    python = str(searxng.venv_python(home))
    assert commands[0][:2] == ["git", "clone"] and commands[0][-1] == str(home / "src")
    assert commands[1] == [sys.executable, "-m", "venv", str(home / "venv")]
    assert commands[2][:5] == [python, "-m", "pip", "install", "-U"] and "msgspec" in commands[2]
    assert commands[3] == [python, "-m", "pip", "install", "--use-pep517", "--no-build-isolation",
                           "-e", str(home / "src")]
    assert searxng.installed(home)
    text = (home / "settings.yml").read_text()
    assert 'bind_address: "127.0.0.1"' in text and "port: 8888" in text and "- json" in text


def test_installing_again_updates_instead_of_cloning(home, commands):
    install(home)
    commands.clear()
    install(home)
    assert commands[0][:4] == ["git", "-C", str(home / "src"), "pull"]
    assert not any(c[1:3] == ["-m", "venv"] for c in commands)  # the venv is kept


def test_a_failed_step_never_counts_as_installed(home, commands, monkeypatch):
    async def fail(command, log, cwd=None):
        raise searxng.SearxngError("This step failed.")

    monkeypatch.setattr(searxng, "run", fail)
    with pytest.raises(searxng.SearxngError):
        install(home)
    assert not searxng.installed(home)


def test_settings_keep_your_own_changes(home):
    home.mkdir()
    (home / "settings.yml").write_text("my own settings")
    searxng.write_settings(home)
    assert (home / "settings.yml").read_text() == "my own settings"


def test_the_secret_is_random(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = searxng.write_settings(tmp_path / "a").read_text()
    second = searxng.write_settings(tmp_path / "b").read_text()
    assert "{secret}" not in first and first != second


@pytest.mark.parametrize("platform_name, path", [
    ("linux", "venv/bin/python"),
    ("darwin", "venv/bin/python"),
    ("win32", "venv/Scripts/python.exe"),
])
def test_the_venv_python_on_every_system(monkeypatch, home, platform_name, path):
    monkeypatch.setattr(searxng.sys, "platform", platform_name)
    assert searxng.venv_python(home) == home / path


def test_what_can_stop_an_install(monkeypatch):
    monkeypatch.setattr(searxng.shutil, "which", lambda name: None)
    assert "needs Git" in searxng.can_install()
    monkeypatch.setattr(searxng.sys, "frozen", True, raising=False)
    assert "packaged app" in searxng.can_install()


def test_cerberus_starts_its_searxng_only_when_web_search_uses_it(db, home, commands, monkeypatch):
    started = []

    async def start(home=None):
        started.append(True)

    monkeypatch.setattr(searxng, "start", start)
    monkeypatch.setattr(searxng, "HOME", home)

    asyncio.run(searxng.start_saved())  # not installed
    install(home)
    settings.update({"web_engine": "duckduckgo"})
    asyncio.run(searxng.start_saved())  # another engine
    settings.update({"web_engine": "searxng", "web_url": "http://192.168.1.5:8080"})
    asyncio.run(searxng.start_saved())  # another SearXNG
    assert started == []

    settings.update({"web_url": searxng.URL})
    asyncio.run(searxng.start_saved())
    assert started == [True]


def test_another_searxng_already_answering_is_left_alone(home, monkeypatch):
    async def answers(url):
        return "ok"

    monkeypatch.setattr(searxng, "searxng_check", answers)
    monkeypatch.setattr(searxng.subprocess, "Popen", lambda *a, **k: pytest.fail("started a second one"))
    asyncio.run(searxng.start(home))
    assert searxng.process is None


def test_the_install_route_chooses_and_starts_searxng(client, monkeypatch):
    async def fake_install():
        yield {"step": "download"}
        yield {"step": "done"}

    async def fake_start(home=None):
        pass

    monkeypatch.setattr(searxng, "install", fake_install)
    monkeypatch.setattr(searxng, "start", fake_start)
    settings.update({"web_engine": "duckduckgo"})

    lines = client.post("/setup/searxng/install").text.splitlines()

    assert lines[-1] == '{"step": "running"}'
    assert settings.get("web_engine") == "searxng" and settings.get("web_url") == searxng.URL


def test_a_failed_install_is_reported_in_the_stream(client, monkeypatch):
    async def broken():
        yield {"step": "download"}
        raise searxng.SearxngError("This step failed. The details are in install.log.")

    monkeypatch.setattr(searxng, "install", broken)
    last = client.post("/setup/searxng/install").text.splitlines()[-1]
    assert '"step": "error"' in last and "install.log" in last


# ---------- The on/off switch ----------


@pytest.fixture
def docker(monkeypatch):
    """A fake docker command with one container. state: what inspect says."""
    fake = {"state": "running", "ran": []}

    def run_docker(*args):
        fake["ran"].append(args)
        if fake["state"] == "no_permission":
            return subprocess.CompletedProcess(args, 1, "", "permission denied while trying to connect")
        if fake["state"] == "missing":
            return subprocess.CompletedProcess(args, 1, "", "Error: No such object: searxng")
        if args[0] == "inspect":
            return subprocess.CompletedProcess(args, 0, "true\n" if fake["state"] == "running" else "false\n", "")
        fake["state"] = "running" if args[0] == "start" else "stopped"
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(searxng, "run_docker", run_docker)
    monkeypatch.setattr(searxng.shutil, "which", lambda name: "/usr/bin/" + name)
    return fake


def test_docker_state_reads_what_docker_says(docker):
    for state in ["running", "stopped", "missing", "no_permission"]:
        docker["state"] = state
        assert searxng.docker_state() == state


def test_the_switch_stops_and_starts_a_docker_searxng(db, docker, tmp_path, monkeypatch):
    monkeypatch.setattr(searxng, "HOME", tmp_path / "not-installed")

    assert asyncio.run(searxng.switch(False)) == ""
    assert docker["state"] == "stopped" and settings.get("searxng_on") == "no"
    assert ("stop", "-t", "5", "searxng") in docker["ran"]

    assert asyncio.run(searxng.switch(True)) == ""
    assert docker["state"] == "running" and settings.get("searxng_on") == "yes"


@pytest.mark.parametrize("platform_name, command", [
    ("linux", "sudo docker stop searxng"), ("darwin", "docker stop searxng")])
def test_when_docker_needs_sudo_the_switch_gives_the_command(db, docker, tmp_path, monkeypatch,
                                                            platform_name, command):
    monkeypatch.setattr(searxng, "HOME", tmp_path / "not-installed")
    monkeypatch.setattr(searxng.websearch.sys, "platform", platform_name)
    docker["state"] = "no_permission"
    assert asyncio.run(searxng.switch(False)) == command
    assert settings.get("searxng_on") == "no"  # the choice is saved anyway


def test_cerberus_stops_searxng_when_it_closes_only_when_on(db, docker, tmp_path, monkeypatch):
    monkeypatch.setattr(searxng, "HOME", tmp_path / "not-installed")
    settings.update({"searxng_on": "no"})
    searxng.stop_saved()
    assert docker["state"] == "running"  # off: Cerberus doesn't touch it

    settings.update({"searxng_on": "yes"})
    searxng.stop_saved()
    assert docker["state"] == "stopped"

    asyncio.run(searxng.start_saved())
    assert docker["state"] == "running"  # and starts it with Cerberus


def test_switched_off_searxng_is_never_asked(db, monkeypatch):
    from cerberus.search import websearch

    settings.update({"searxng_on": "no"})
    monkeypatch.setattr(websearch, "new_client", lambda timeout: pytest.fail("asked SearXNG"))
    with pytest.raises(websearch.WebError, match="switched off"):
        asyncio.run(websearch.search("x"))


def test_the_switch_route(client, docker, tmp_path, monkeypatch):
    monkeypatch.setattr(searxng, "HOME", tmp_path / "not-installed")
    docker["state"] = "no_permission"
    answer = client.post("/setup/searxng/switch", json={"on": False}).json()
    assert answer["on"] is False and answer["command"].endswith("docker stop searxng")


def test_switching_off_cerberuss_own_searxng_leaves_docker_alone(db, docker, monkeypatch):
    class Running:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout):
            pass

    monkeypatch.setattr(searxng, "process", Running())
    assert asyncio.run(searxng.switch(False)) == ""
    assert searxng.process is None and docker["ran"] == []
