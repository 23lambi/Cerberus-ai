# Tests for running on Linux, macOS and Windows. Only Linux runs these
# tests here, so each system is described to the functions instead:
# "platform" is what sys.platform says on it, "environ" its variables.

from pathlib import Path

import pytest

import desktop
from cerberus.core import config

HOME = Path("/home/you")


@pytest.mark.parametrize("platform, environ, expected", [
    ("linux", {}, HOME / ".local/share/cerberus"),
    ("linux", {"XDG_DATA_HOME": "/data"}, Path("/data/cerberus")),
    ("darwin", {}, HOME / "Library/Application Support/Cerberus"),
    ("win32", {"LOCALAPPDATA": "C:/Users/you/AppData/Local"}, Path("C:/Users/you/AppData/Local/Cerberus")),
    ("win32", {}, HOME / "AppData/Local/Cerberus"),  # the variable is missing: its usual place
])
def test_each_system_keeps_data_in_its_own_place(platform, environ, expected):
    assert config.system_data_dir(platform, environ, HOME) == expected


def test_an_existing_database_in_the_project_stays_where_it_is(tmp_path):
    # Older installs: cerberus.db is in the project folder. It must not move.
    (tmp_path / "cerberus.db").write_bytes(b"")
    assert config.data_dir({}, tmp_path, "linux", HOME) == tmp_path


def test_a_new_install_uses_the_systems_place(tmp_path):
    assert config.data_dir({}, tmp_path, "darwin", HOME) == HOME / "Library/Application Support/Cerberus"


def test_cerberus_data_wins_over_everything(tmp_path):
    (tmp_path / "cerberus.db").write_bytes(b"")
    assert config.data_dir({"CERBERUS_DATA": "/mnt/usb/cerberus"}, tmp_path, "win32", HOME) == Path("/mnt/usb/cerberus")


@pytest.mark.parametrize("platform, gui", [
    ("linux", "qt"),  # Linux has no built-in engine: the Qt one we installed
    ("win32", None),  # pywebview picks WebView2 (Edge) by itself
    ("darwin", None),  # pywebview picks WebKit (Safari) by itself
])
def test_each_system_gets_its_browser_engine(platform, gui):
    assert desktop.choose_gui(platform) == gui


def test_the_page_is_found_from_any_folder(client, monkeypatch, tmp_path):
    # The page used to be found as "static/..." relative to the current
    # folder; started from elsewhere, it was missing.
    monkeypatch.chdir(tmp_path)
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert "data_dir" in client.get("/about").json()


def test_interface_assets_get_new_urls_when_their_contents_change(client, monkeypatch, tmp_path):
    import re
    from cerberus.routes import pages

    (tmp_path / "index.html").write_text(
        '<link href="/static/style.css" rel="stylesheet"><script src="/static/app.js"></script>',
        encoding="utf-8",
    )
    (tmp_path / "style.css").write_text("body { color: red; }")
    script = tmp_path / "app.js"
    script.write_text("old()")
    monkeypatch.setattr(pages, "STATIC_DIR", tmp_path)
    first = client.get("/")
    assert first.status_code == 200
    assert first.headers["content-type"].startswith("text/html")
    assert first.headers["cache-control"] == "no-cache"
    assert client.get("/").text == first.text
    script.write_text("new()")  # Same length, potentially the same timestamp.
    second = client.get("/")
    urls = lambda response: re.findall(r'/static/[^" ]+', response.text)
    first_urls, second_urls = urls(first), urls(second)
    assert all("?v=" in url for url in first_urls)
    assert first_urls[0] == second_urls[0]  # Unchanged CSS keeps its URL.
    assert first_urls[1] != second_urls[1]


def test_window_takes_over_when_the_other_windows_server_stops(monkeypatch):
    # The other window's server answers twice, then its window closes.
    answers = iter([True, True, False])
    monkeypatch.setattr(desktop, "already_running", lambda: next(answers))
    monkeypatch.setattr(desktop.time, "sleep", lambda seconds: None)
    started = []
    monkeypatch.setattr(desktop, "start_server", lambda: started.append(1) or ("server", "thread"))
    loaded = []
    window = type("Window", (), {"load_url": lambda self, url: loaded.append(url)})()
    ours = []
    desktop.take_over_when_gone(window, ours)
    assert ours == ["server", "thread"]  # stopped again when this window closes
    assert started == [1] and loaded == [desktop.address()]


def test_about_says_whether_a_window_owns_the_server(client, monkeypatch):
    assert client.get("/about").json()["window"] is False  # uvicorn by hand, or tests
    monkeypatch.setenv("CERBERUS_WINDOW", "1")
    assert client.get("/about").json()["window"] is True
