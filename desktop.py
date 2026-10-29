# Cerberus as a desktop app: its own window, instead of a browser tab.
# Run it with:  venv/bin/python desktop.py   (Windows: venv\Scripts\python desktop.py)
# install-desktop.sh (Linux, macOS) or install-desktop.ps1 (Windows) puts
# it in your app menu, with the icon.
#
# The app is the same web page as always. This file only:
#   1. starts the Cerberus server in the background (unless it's already running)
#   2. shows the page in a window, with pywebview and a browser engine
#   3. stops the server again when you close the window
#
# The browser engine depends on the system (see choose_gui):
#   Windows: WebView2 (Edge), built into Windows 10 and 11
#   macOS:   WebKit (Safari), built into macOS
#   Linux:   Qt WebEngine, installed with pip (Linux has none built in)

import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Older installs keep documents at the relative path "documents/" in the
# project folder, so the app runs from there, wherever it was started from.
os.chdir(HERE)

import uvicorn  # noqa: E402  (imported after chdir on purpose)
import webview  # noqa: E402

from cerberus.core.config import system_data_dir  # noqa: E402

HOST = "127.0.0.1"  # only this computer can reach it
PORT = int(os.environ.get("CERBERUS_PORT", "8000"))
DOWNLOADS = Path.home() / "Downloads"
# Where the window keeps its own browser data (like the chosen model), so
# it's remembered between starts. Always in the system's app folder: it's
# the window's cache, not your chats.
STORAGE = system_data_dir() / "webview"


def choose_gui(platform=sys.platform):
    """pywebview's engine for this system. None = its own pick, the built-in one."""
    # Windows and macOS have a browser engine built in, and pywebview picks
    # it by itself. Linux has none, so we name the one we installed.
    return "qt" if platform.startswith("linux") else None


def address():
    return f"http://{HOST}:{PORT}/"


def running_server():
    """What Cerberus on the port says about itself (/about), or None."""
    try:
        with urllib.request.urlopen(address() + "about", timeout=1) as response:
            about = json.load(response)
        return about if about.get("name") == "Cerberus" else None
    except (OSError, ValueError, AttributeError):
        return None


def already_running():
    """True when Cerberus already answers on the port (another window, or uvicorn by hand)."""
    return running_server() is not None


def take_over_when_gone(window, ours):
    """This window uses another Cerberus window's server. Closing that window
    stops its server; then this one starts its own and reloads, instead of
    showing "Failed to fetch" everywhere. ours keeps the new server, so it
    is stopped again when this window closes."""
    while not ours:
        time.sleep(1)
        if already_running():
            continue
        try:
            ours.extend(start_server())
        except SystemExit:
            continue  # something else took the port: check again
        window.load_url(address())


def wait_for_previous_version():
    """After an in-app update, the new version starts while the old one closes."""
    if os.environ.pop("CERBERUS_REPLACES", None):
        for _ in range(600):  # up to a minute: a running answer may be saving
            if not already_running():
                return
            time.sleep(0.1)


def start_server():
    """Start Cerberus in a background thread. Returns the server, to stop it later."""
    from main import app

    # One server, one worker: Stop and the active answers live in this process.
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_level="warning", log_config=None))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # Managed llama.cpp may spend up to two minutes loading a model.
    # Wait until startup finishes so the window never opens on an empty page.
    for _ in range(3000):
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


def use_qt():
    """The Qt-only parts: our download fix and the app's name on Linux desktops."""
    # The Qt part of pywebview calls this method for every download. We
    # swap in our own before any window exists (see save_download). On
    # Windows and macOS, pywebview's own downloads already work well.
    from webview.platforms import qt

    qt.BrowserView.on_download_requested = save_download

    # On Wayland, the desktop finds the window's icon and app-menu entry by
    # this name: it matches cerberus.desktop from install-desktop.sh.
    from qtpy.QtGui import QGuiApplication

    QGuiApplication.setDesktopFileName("cerberus")


def main():
    # /about tells other windows that this server belongs to a window
    # (pages.py), so they may take over when this window closes.
    os.environ["CERBERUS_WINDOW"] = "1"
    ours = []  # [server, thread] when this window runs the server
    wait_for_previous_version()
    other = running_server()
    if not other:
        ours.extend(start_server())

    gui = choose_gui()
    if gui == "qt":
        use_qt()
    webview.settings["ALLOW_DOWNLOADS"] = True  # backups and chat exports
    # Links to other sites (a web source, VirusTotal) open in your normal
    # browser, never inside Cerberus.
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True

    window = webview.create_window(
        "Cerberus",
        address(),
        width=1320,
        height=880,
        min_size=(900, 600),
        background_color="#17181d",  # the app's own dark color while loading
        confirm_close=False,
    )
    if other and other.get("window"):
        # Not when you run uvicorn by hand: during --reload it is briefly
        # gone, and this window must not take its port.
        threading.Thread(target=take_over_when_gone, args=(window, ours), daemon=True).start()
    STORAGE.mkdir(parents=True, exist_ok=True)
    webview.start(
        gui=gui,
        private_mode=False,  # keep the browser data (model choice, Web pill)
        storage_path=str(STORAGE),
        # The window icon. Only Linux uses this; Windows and macOS take
        # the icon from the shortcut or the .app (see the install scripts).
        icon=str(HERE / "static" / "cerberus.svg"),
    )

    # The window is closed. Stop the server we started (not one you
    # started by hand), and give a running answer a moment to save.
    if ours:
        server, thread = ours
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == "__main__":
    main()
