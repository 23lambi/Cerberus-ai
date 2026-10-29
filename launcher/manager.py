"""Release discovery, verified installation, and application lifecycle.

This module intentionally does not import Cerberus or third-party packages:
the launcher must work before the application has been installed.
"""

import contextlib
import hashlib
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPOSITORY = "23lambi/Cerberus-ai"
RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
VERSION = re.compile(r"v?\d+\.\d+\.\d+(?:[-.][A-Za-z0-9]+)*\Z")
TARGETS = {"linux-x86_64", "windows-x86_64", "macos-x86_64", "macos-arm64"}
MAX_DOWNLOAD = 2 * 1024**3
MAX_UNPACKED = 5 * 1024**3


class LauncherError(Exception):
    """An actionable error suitable for display in the launcher."""


def target_name(system=None, machine=None):
    system = system or sys.platform
    machine = (machine or platform.machine()).lower()
    architecture = {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    name = "linux" if system.startswith("linux") else {"win32": "windows", "darwin": "macos"}.get(system)
    target = f"{name}-{architecture}"
    if target not in TARGETS:
        raise LauncherError("No downloadable build is available for this operating system and processor yet.")
    return target


def data_base(system=None, environ=None, home=None):
    system = system or sys.platform
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    if system == "win32":
        return Path(environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    if system == "darwin":
        return home / "Library" / "Application Support"
    return Path(environ.get("XDG_DATA_HOME", home / ".local" / "share"))


def install_directory(system=None, environ=None, home=None):
    system = system or sys.platform
    return data_base(system, environ, home) / ("cerberus-launcher" if system.startswith("linux") else "CerberusLauncher")


def location_file():
    """Remembers the install folder the user chose; always at the default place."""
    return install_directory() / "location.json"


def saved_root():
    try:
        root = Path(json.loads(location_file().read_text())["root"])
        return root if root.is_absolute() else install_directory()
    except (OSError, ValueError, TypeError, KeyError):
        return install_directory()


def save_root(root):
    path = location_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"root": str(root)}))


def forget_root():
    location_file().unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        install_directory().rmdir()  # only when nothing else is left there


def root_in(folder):
    """The install root for a folder the user picked.

    A folder that is empty or already holds Cerberus is used as is; any other
    folder gets its own Cerberus subfolder, so uninstall never touches the
    user's files.
    """
    folder = Path(folder).expanduser()
    if (folder / "installation.json").is_file():
        return folder
    if folder.is_dir() and not any(folder.iterdir()):
        return folder
    return folder / "Cerberus"


def check_writable(root):
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / f".write-test-{uuid.uuid4().hex}"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError:
        raise LauncherError(f"Cerberus cannot write to {root}. Choose a folder in your user account.") from None


def installed_root(executable, target):
    """The install root of a launcher-installed app, from its own executable path."""
    depth = 5 if target.startswith("macos-") else 3  # .../versions/<id>/Cerberus.app/Contents/MacOS/Cerberus
    executable = Path(executable).resolve()
    if len(executable.parents) <= depth:
        return None
    root = executable.parents[depth]
    if executable.parents[depth - 1].name != "versions" or not (root / "installation.json").is_file():
        return None
    return root


def child_environment(extra):
    """Environment for starting another frozen program from a frozen one."""
    env = {**os.environ, **extra}
    # Without this, a PyInstaller child may reuse its parent's unpacked files.
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
    elif getattr(sys, "frozen", False):
        env.pop("LD_LIBRARY_PATH", None)
    return env


def start_detached(args, env, log):
    """Start a program that keeps running after this one exits."""
    options = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if sys.platform == "win32" else {"start_new_session": True}
    return subprocess.Popen(args, cwd=Path(args[0]).parent, env=env, stdin=subprocess.DEVNULL,
                            stdout=log, stderr=log, **options)


def app_data_directory():
    explicit = os.environ.get("CERBERUS_DATA")
    if explicit:
        return Path(explicit).expanduser()
    return data_base() / ("cerberus" if sys.platform.startswith("linux") else "Cerberus")


def executable_path(folder, target):
    if target.startswith("macos-"):
        return folder / "Cerberus.app" / "Contents" / "MacOS" / "Cerberus"
    return folder / "Cerberus" / ("Cerberus.exe" if target.startswith("windows-") else "Cerberus")


def release_url(tag, name):
    if not VERSION.fullmatch(tag):
        raise LauncherError("The release version is invalid.")
    return f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"


# Where Linux distributions and macOS keep their trusted certificates.
CERTIFICATE_FILES = (
    "/etc/ssl/certs/ca-certificates.crt",  # Debian, Ubuntu, Arch
    "/etc/pki/tls/certs/ca-bundle.crt",  # Fedora, RHEL
    "/etc/ssl/ca-bundle.pem",  # openSUSE
    "/etc/ssl/cert.pem",  # Alpine, macOS
)


def tls_context(candidates=CERTIFICATE_FILES):
    """Verified HTTPS on every system.

    The bundled OpenSSL looks for certificates where the build machine
    (Ubuntu) keeps them. Other systems keep them elsewhere, so when none
    were found, use the system's own file from its usual place.
    """
    context = ssl.create_default_context()
    if not context.cert_store_stats()["x509_ca"]:
        for path in candidates:
            if os.path.isfile(path):
                context.load_verify_locations(cafile=path)
                break
    return context


def open_url(url, timeout=30):
    request = urllib.request.Request(url, headers={"User-Agent": "Cerberus-Launcher", "Accept": "application/json"})
    return urllib.request.urlopen(request, timeout=timeout, context=tls_context())


def read_json(url):
    try:
        with open_url(url) as response:
            data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise LauncherError("The release information is too large.")
        return json.loads(data)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise LauncherError("No downloadable release is published yet. Try again after the first release is available.") from None
        raise LauncherError(f"GitHub returned error {error.code}. Please try again later.") from None
    except (OSError, ValueError) as error:
        raise LauncherError(f"Could not check releases: {error}") from None


def latest_release(target):
    release = read_json(RELEASE_API)
    if not isinstance(release, dict) or not VERSION.fullmatch(str(release.get("tag_name", ""))):
        raise LauncherError("GitHub returned invalid release information.")
    tag = release["tag_name"]
    if release.get("draft") or release.get("prerelease"):
        raise LauncherError("A stable application release is not available yet.")
    manifest = read_json(release_url(tag, "release-manifest.json"))
    if not isinstance(manifest, dict) or manifest.get("version") != tag:
        raise LauncherError("The release manifest does not match its version.")
    builds = manifest.get("builds")
    build = builds.get(target) if isinstance(builds, dict) else None
    expected = f"cerberus-{target}.tar.gz"
    if not isinstance(build, dict) or build.get("file") != expected:
        raise LauncherError("This release does not include a build for your computer.")
    digest = build.get("sha256", "")
    size = build.get("size")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise LauncherError("The release checksum is missing or invalid.")
    if type(size) is not int or not 0 < size <= MAX_DOWNLOAD:
        raise LauncherError("The release download size is invalid.")
    return {"version": tag, "target": target, "file": expected, "sha256": digest,
            "size": size, "url": release_url(tag, expected)}


@contextlib.contextmanager
def operation_lock(root):
    """An OS-backed lock is released even if a launcher process crashes."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / "operation.lock").open("a+b") as lock:
        if lock.seek(0, 2) == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise LauncherError("Another launcher is making changes. Wait for it to finish.") from None
        try:
            yield
        finally:
            if sys.platform == "win32":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def download(build, destination, progress, cancelled):
    digest = hashlib.sha256()
    size = 0
    try:
        with open_url(build["url"]) as response, destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                if cancelled():
                    raise LauncherError("Download cancelled. Your current installation is unchanged.")
                size += len(chunk)
                if size > build["size"] or size > MAX_DOWNLOAD:
                    raise LauncherError("The download exceeds its expected size.")
                output.write(chunk)
                digest.update(chunk)
                progress("Downloading Cerberus", size, build["size"])
    except OSError as error:
        raise LauncherError(f"The download stopped: {error}. Please try again.") from None
    if size != build["size"] or digest.hexdigest() != build["sha256"]:
        raise LauncherError("Download verification failed. Nothing was installed. Please try again.")
    if cancelled():
        raise LauncherError("Download cancelled. Your current installation is unchanged.")


def unpack(archive, destination):
    try:
        with tarfile.open(archive, "r:gz") as package:
            members = package.getmembers()
            if len(members) > 100000 or sum(member.size for member in members) > MAX_UNPACKED:
                raise LauncherError("The application archive exceeds its allowed size.")
            # data refuses escaping paths, unsafe links, and special device files.
            package.extractall(destination, members=members, filter="data")
    except (tarfile.TarError, OSError) as error:
        raise LauncherError(f"Could not unpack the application: {error}") from None


def server_running():
    try:
        port = int(os.environ.get("CERBERUS_PORT", "8000"))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/about", timeout=1) as response:
            return json.load(response).get("name") == "Cerberus"
    except (OSError, ValueError, AttributeError):
        return False


class Manager:
    def __init__(self, root=None, target=None):
        self.root = Path(root) if root is not None else install_directory()
        self.target = target or target_name()
        if self.target not in TARGETS:
            raise LauncherError("Unsupported application build.")
        self.process = None

    def state(self):
        path = self.root / "installation.json"
        if not path.exists():
            return None
        try:
            state = json.loads(path.read_text())
            if (not VERSION.fullmatch(state["version"]) or state["target"] != self.target
                    or not re.fullmatch(r"[0-9a-f]{32}", state["build"])):
                raise ValueError("invalid installation record")
            return state
        except (OSError, ValueError, TypeError, KeyError):
            raise LauncherError("The installation record is damaged. Install again to repair it.") from None

    def installation_path(self, state):
        return self.root / "versions" / (state["version"] + "-" + state["build"])

    def running(self):
        return (self.process is not None and self.process.poll() is None) or server_running()

    def executable(self, state=None):
        state = state or self.state()
        return executable_path(self.installation_path(state), self.target) if state else None

    def install(self, build, progress=lambda *_: None, cancelled=lambda: False, from_app=False):
        """Install a release beside the current one, then switch to it.

        from_app: the running app updates itself. Its own version folder is
        left alone; the new one is used from its next start.
        """
        if build["target"] != self.target or not VERSION.fullmatch(build["version"]):
            raise LauncherError("This download is not for your computer.")
        with operation_lock(self.root):
            if not from_app and self.running():
                raise LauncherError("Close Cerberus before installing or updating it.")
            versions = self.root / "versions"
            versions.mkdir(exist_ok=True)
            if from_app:
                self.prune()
            state = {"version": build["version"], "target": self.target, "build": uuid.uuid4().hex}
            installed = self.installation_path(state)
            pointer = self.root / "installation.json"
            pointer_temp = self.root / "installation.new"
            with tempfile.TemporaryDirectory(prefix="download-", dir=self.root) as temporary:
                temp = Path(temporary)
                archive = temp / "application.tar.gz"
                download(build, archive, progress, cancelled)
                progress("Unpacking application", 0, 0)
                staged = temp / "app"
                staged.mkdir()
                unpack(archive, staged)
                executable = executable_path(staged, self.target)
                if not executable.is_file():
                    raise LauncherError("The download does not contain the application where expected.")
                if cancelled():
                    raise LauncherError("Installation cancelled. Your current installation is unchanged.")
                if not self.target.startswith("windows-"):
                    executable.chmod(executable.stat().st_mode | 0o755)
                try:
                    staged.rename(installed)
                    with pointer_temp.open("w") as output:
                        json.dump(state, output)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(pointer_temp, pointer)
                except OSError as error:
                    shutil.rmtree(installed, ignore_errors=True)
                    raise LauncherError(f"Could not finish installation: {error}") from None
                finally:
                    pointer_temp.unlink(missing_ok=True)
            return state

    def prune(self, running=None):
        """Remove old versions, except the selected one and the running one."""
        versions = self.root / "versions"
        state = self.state()
        if versions.is_symlink() or not versions.is_dir() or not state:
            return
        running = Path(running or sys.executable).resolve()
        keep = {self.installation_path(state).name}
        if running.is_relative_to(versions.resolve()):
            keep.add(running.relative_to(versions.resolve()).parts[0])
        for folder in versions.iterdir():
            if folder.name not in keep and not folder.is_symlink():
                shutil.rmtree(folder, ignore_errors=True)

    def launch(self):
        with operation_lock(self.root):
            if self.running():
                raise LauncherError("Cerberus is already running. Switch to its window.")
            state = self.state()
            if not state:
                raise LauncherError("Install Cerberus first.")
            executable = self.executable(state)
            if not executable.is_file():
                raise LauncherError("The application is missing. Install it again to repair it.")
            env = child_environment({"CERBERUS_DATA": str(app_data_directory())})
            with (self.root / "app.log").open("ab") as log:
                self.process = start_detached([str(executable)], env, log)
            return self.process

    def uninstall(self):
        with operation_lock(self.root):
            if self.running():
                raise LauncherError("Close Cerberus before uninstalling it.")
            versions = self.root / "versions"
            if versions.is_symlink():
                raise LauncherError("The installation directory is a link. Remove it manually.")
            if versions.exists():
                shutil.rmtree(versions)
            (self.root / "installation.json").unlink(missing_ok=True)
