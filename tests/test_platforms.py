# Tests for running on Linux, macOS and Windows. Only Linux runs these
# tests here, so each system is described to the functions instead:
# "platform" is what sys.platform says on it, "environ" its variables.

from pathlib import Path

import pytest

import desktop
from cerberus import config

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
