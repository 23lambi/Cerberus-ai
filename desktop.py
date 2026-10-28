# Cerberus as a desktop app: its own window, instead of a browser tab.
# Run it with:  venv/bin/python desktop.py
# (install-desktop.sh puts it in your app menu, with the icon.)
#
# The app is the same web page as always. This file only:
#   1. starts the Cerberus server in the background (unless it's already running)
#   2. shows the page in a window, using pywebview with Qt's browser engine
#   3. stops the server again when you close the window

import json
import os
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
# cerberus.db, documents/ and static/ are found relative to the project
# folder, so the app must run from there, wherever it was started from.
os.chdir(HERE)

import uvicorn  # noqa: E402  (imported after chdir on purpose)
import webview  # noqa: E402

HOST = "127.0.0.1"  # only this computer can reach it
PORT = int(os.environ.get("CERBERUS_PORT", "8000"))
DOWNLOADS = Path.home() / "Downloads"
# Where the window keeps its own browser data (like the chosen model),
# so it's remembered between starts.
STORAGE = Path.home() / ".local/share/cerberus-desktop"


def address():
    return f"http://{HOST}:{PORT}/"


def already_running():
    """True when Cerberus already answers on the port (started by hand with uvicorn)."""
    try:
        with urllib.request.urlopen(address() + "about", timeout=1) as response:
            return json.load(response).get("name") == "Cerberus"
    except (OSError, ValueError):
        return False


def start_server():
    """Start Cerberus in a background thread. Returns the server, to stop it later."""
    from main import app

    # One server, one worker: Stop and the active answers live in this process.
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # Wait until it really listens (at most 10 seconds), so the window
    # never opens on an empty page.
    for _ in range(200):
        if server.started:
            return server, thread
        if not thread.is_alive():
            break  # it stopped by itself: the port is taken by another program
        time.sleep(0.05)
    raise SystemExit(f"Cerberus could not start on port {PORT}. Is another program using it?")


def save_download(view, download):
    """Backups and chat exports go to ~/Downloads, under the server's file name.

    pywebview has its own version of this, but it's written for Qt 5
    (download.setPath no longer exists in Qt 6) and names the file after
    the address (/backup) instead of the real name. So we replace it.
    """
    DOWNLOADS.mkdir(exist_ok=True)
    name = download.suggestedFileName()  # from the server, like cerberus-backup-....zip
    download.setDownloadDirectory(str(DOWNLOADS))
    download.setDownloadFileName(name)

    def finished():
        if download.isFinished():
            # json.dumps makes the text a safe JavaScript string.
            message = json.dumps(f"Saved to {DOWNLOADS / name}")
            view.webview.page().runJavaScript(f"alert({message})")

    download.isFinishedChanged.connect(finished)
    download.accept()


def main():
    server = None
    if not already_running():
        server, thread = start_server()

    # The Qt part of pywebview calls this method for every download. We
    # swap in our own before any window exists (see save_download).
    from webview.platforms import qt

    qt.BrowserView.on_download_requested = save_download
    webview.settings["ALLOW_DOWNLOADS"] = True
    # Links to other sites (a web source, VirusTotal) open in your normal
    # browser, never inside Cerberus.
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True

    # On Wayland, the desktop finds the window's icon and app-menu entry by
    # this name: it matches cerberus.desktop from install-desktop.sh.
    from qtpy.QtGui import QGuiApplication

    QGuiApplication.setDesktopFileName("cerberus")

    webview.create_window(
        "Cerberus",
        address(),
        width=1320,
        height=880,
        min_size=(900, 600),
        background_color="#17181d",  # the app's own dark color while loading
        confirm_close=False,
    )
    STORAGE.mkdir(parents=True, exist_ok=True)
    webview.start(
        gui="qt",
        private_mode=False,  # keep the browser data (model choice, Web pill)
        storage_path=str(STORAGE),
        icon=str(HERE / "static" / "cerberus.svg"),
    )

    # The window is closed. Stop the server we started (not one you
    # started by hand), and give a running answer a moment to save.
    if server is not None:
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == "__main__":
    main()
