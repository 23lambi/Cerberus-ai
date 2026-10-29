# Updates inside the app (Settings → Updates).
#
# Only the packaged app installed by the launcher can update itself. It
# downloads the new version next to the one that is running, using the
# launcher's own checked installer (launcher/manager.py), and switches to
# it on restart. Run from source, Cerberus updates with git pull instead.

import os
import sys
import threading
import time
from pathlib import Path

from cerberus.core.version import VERSION
from launcher import manager as installer
from launcher.presentation import is_newer
from launcher.shortcuts import launcher_executable

_lock = threading.Lock()
_job = {"state": "idle", "latest": None, "done": 0, "total": 0, "message": ""}
_release = None


def installation():
    """The launcher's Manager for this app, or None when run from source."""
    if not getattr(sys, "frozen", False):
        return None
    try:
        target = installer.target_name()
        root = installer.installed_root(Path(sys.executable), target)
        return installer.Manager(root, target) if root else None
    except installer.LauncherError:
        return None


def status():
    with _lock:
        return {"managed": installation() is not None, "current": VERSION, **_job}


def _set(**values):
    with _lock:
        _job.update(values)


def check():
    """Ask GitHub for the newest release. Raises LauncherError when offline."""
    global _release
    manager = installation()
    if manager is None:
        return status()
    release = installer.latest_release(manager.target)
    _release = release
    with _lock:
        if _job["state"] in ("idle", "error", "current", "available"):
            newer = is_newer(release["version"], VERSION)
            _job.update(state="available" if newer else "current", latest=release["version"],
                        total=release["size"], done=0, message="")
    return status()


def start_download():
    manager = installation()
    with _lock:
        if manager is None or _release is None or _job["state"] != "available":
            return False
        _job.update(state="downloading", done=0, message="")
    release = _release

    def progress(_text, done, total):
        _set(done=done, total=total or release["size"])

    def work():
        try:
            manager.install(release, progress, from_app=True)
            _set(state="ready", done=release["size"])
        except installer.LauncherError as error:
            _set(state="error", message=str(error))
    threading.Thread(target=work, daemon=True).start()
    return True


def _close_windows():
    # A moment first, so the page receives the answer before the window goes.
    time.sleep(0.5)
    import webview
    for window in list(webview.windows):
        window.destroy()


def _start(args, extra_env):
    manager = installation()
    with (manager.root / "app.log").open("ab") as log:
        installer.start_detached([str(arg) for arg in args], installer.child_environment(extra_env), log)
    threading.Thread(target=_close_windows, daemon=True).start()


def restart():
    """Start the newly installed version, then close this one."""
    manager = installation()
    if manager is None or _job["state"] != "ready":
        return False
    # The new app waits until this one has stopped its server (see desktop.py).
    _start([manager.executable()], {"CERBERUS_REPLACES": str(os.getpid())})
    return True


def uninstall():
    """Hand over to the launcher, which removes the app once this one is closed."""
    manager = installation()
    if manager is None:
        return False
    launcher = launcher_executable(manager.root)
    if not launcher.is_file():
        raise installer.LauncherError("The Cerberus launcher was not found. Download it again to uninstall.")
    _start([launcher, "--uninstall"], {})
    return True
