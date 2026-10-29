"""Installer tests use generated archives and temporary directories only."""
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from launcher import manager as launcher


@pytest.mark.parametrize("system,machine,target", [
    ("linux", "x86_64", "linux-x86_64"), ("win32", "AMD64", "windows-x86_64"),
    ("darwin", "x86_64", "macos-x86_64"), ("darwin", "arm64", "macos-arm64"),
])
def test_platform_selection(system, machine, target):
    assert launcher.target_name(system, machine) == target


def test_unsupported_architecture_is_explained():
    with pytest.raises(launcher.LauncherError, match="processor"):
        launcher.target_name("linux", "arm64")


@pytest.mark.parametrize("system,expected", [
    ("linux", "/home/test/.local/share/cerberus-launcher"),
    ("win32", "/home/test/AppData/Local/CerberusLauncher"),
    ("darwin", "/home/test/Library/Application Support/CerberusLauncher"),
])
def test_installation_is_separate_from_application_data(system, expected):
    assert str(launcher.install_directory(system, {}, Path('/home/test'))).replace('\\', '/') == expected


def archive_bytes(target="linux-x86_64", content=b"application", extra=None):
    output = io.BytesIO()
    path = str(launcher.executable_path(Path("."), target)).replace('\\', '/')
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        info = tarfile.TarInfo(path)
        info.size = len(content)
        info.mode = 0o755
        archive.addfile(info, io.BytesIO(content))
        if extra:
            archive.addfile(extra)
    return output.getvalue()


@pytest.fixture
def installer(tmp_path, monkeypatch):
    manager = launcher.Manager(tmp_path / "installer", "linux-x86_64")
    monkeypatch.setattr(manager, "running", lambda: False)
    return manager


def build_for(content, version="v0.4.0", target="linux-x86_64"):
    return {"version": version, "target": target, "file": f"cerberus-{target}.tar.gz",
            "url": launcher.release_url(version, f"cerberus-{target}.tar.gz"),
            "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}


def serve(monkeypatch, content):
    monkeypatch.setattr(launcher, "open_url", lambda *a, **kw: io.BytesIO(content))


def test_release_manifest_must_match_tag_and_platform(monkeypatch):
    data = archive_bytes()
    build = build_for(data)
    responses = iter([{"tag_name": "v0.4.0"}, {"version": "v0.4.0", "builds": {build["target"]: build}}])
    monkeypatch.setattr(launcher, "read_json", lambda url: next(responses))
    assert launcher.latest_release("linux-x86_64")["sha256"] == build["sha256"]
    responses = iter([{"tag_name": "v0.4.0"}, {"version": "v9.0.0"}])
    with pytest.raises(launcher.LauncherError, match="does not match"):
        launcher.latest_release("linux-x86_64")


def test_manifest_cannot_change_download_origin(monkeypatch):
    build = build_for(archive_bytes())
    build["url"] = "https://attacker.example/application"
    responses = iter([{"tag_name": "v0.4.0"}, {"version": "v0.4.0", "builds": {build["target"]: build}}])
    monkeypatch.setattr(launcher, "read_json", lambda url: next(responses))
    assert launcher.latest_release(build["target"])["url"].startswith("https://github.com/23lambi/Cerberus-ai/releases/download/")


def test_install_then_update_preserves_previous_version_and_user_data(installer, monkeypatch, tmp_path):
    data_dir = tmp_path / "personal-data"
    data_dir.mkdir()
    (data_dir / "cerberus.db").write_bytes(b"private")
    monkeypatch.setenv("CERBERUS_DATA", str(data_dir))
    first = archive_bytes(content=b"first")
    serve(monkeypatch, first)
    old = installer.install(build_for(first))
    second = archive_bytes(content=b"second")
    serve(monkeypatch, second)
    new = installer.install(build_for(second, "v0.5.0"))
    assert installer.state() == new
    assert launcher.executable_path(installer.installation_path(old), installer.target).read_bytes() == b"first"
    assert launcher.executable_path(installer.installation_path(new), installer.target).read_bytes() == b"second"
    assert (data_dir / "cerberus.db").read_bytes() == b"private"
    installer.uninstall()
    assert installer.state() is None
    assert not (installer.root / "versions").exists()
    assert (data_dir / "cerberus.db").read_bytes() == b"private"


def test_bad_checksum_leaves_current_installation_untouched(installer, monkeypatch):
    data = archive_bytes()
    serve(monkeypatch, data)
    before = installer.install(build_for(data))
    broken = build_for(data, "v0.5.0")
    broken["sha256"] = "0" * 64
    with pytest.raises(launcher.LauncherError, match="verification"):
        installer.install(broken)
    assert installer.state() == before
    assert len(list((installer.root / "versions").iterdir())) == 1


def test_cancelled_download_preserves_current_installation(installer, monkeypatch):
    data = archive_bytes()
    serve(monkeypatch, data)
    before = installer.install(build_for(data))
    with pytest.raises(launcher.LauncherError, match="cancelled"):
        installer.install(build_for(data, "v0.5.0"), cancelled=lambda: True)
    assert installer.state() == before
    assert not list(installer.root.glob("download-*"))


@pytest.mark.parametrize("kind", ["traversal", "symlink"])
def test_escaping_archive_entries_are_rejected(installer, monkeypatch, tmp_path, kind):
    extra = tarfile.TarInfo("../../outside" if kind == "traversal" else "escape")
    if kind == "symlink":
        extra.type = tarfile.SYMTYPE
        extra.linkname = str(tmp_path / "outside")
    data = archive_bytes(extra=extra)
    serve(monkeypatch, data)
    with pytest.raises(launcher.LauncherError, match="unpack"):
        installer.install(build_for(data))
    assert installer.state() is None
    assert not (tmp_path / "outside").exists()


def test_pointer_failure_rolls_back_without_replacing_old_version(installer, monkeypatch):
    data = archive_bytes()
    serve(monkeypatch, data)
    before = installer.install(build_for(data))
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(launcher.os, "replace", fail)
    with pytest.raises(launcher.LauncherError, match="disk full"):
        installer.install(build_for(data, "v0.5.0"))
    assert installer.state() == before
    assert len(list((installer.root / "versions").iterdir())) == 1


def test_second_launcher_cannot_modify_installation(installer):
    with launcher.operation_lock(installer.root):
        with pytest.raises(launcher.LauncherError, match="Another launcher"):
            installer.uninstall()


def test_running_app_blocks_update_and_uninstall(installer, monkeypatch):
    monkeypatch.setattr(installer, "running", lambda: True)
    with pytest.raises(launcher.LauncherError, match="Close Cerberus"):
        installer.install(build_for(archive_bytes()))
    with pytest.raises(launcher.LauncherError, match="Close Cerberus"):
        installer.uninstall()


def test_corrupt_installation_record_cannot_escape_install_root(installer):
    installer.root.mkdir()
    (installer.root / "installation.json").write_text(json.dumps({"version": "../../private", "build": "a" * 32, "target": installer.target}))
    with pytest.raises(launcher.LauncherError, match="damaged"):
        installer.state()


def test_frozen_application_never_uses_database_beside_its_executable(tmp_path, monkeypatch):
    from cerberus.core import config
    (tmp_path / "cerberus.db").write_bytes(b"not user data")
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    assert config.data_dir({}, tmp_path, "linux", Path("/home/test")) == Path("/home/test/.local/share/cerberus")


def test_release_assembly_requires_all_platforms(tmp_path):
    from scripts.release_manifest import create
    with pytest.raises(ValueError, match="Missing platform"):
        create(tmp_path, "v0.4.0")
    for target in launcher.TARGETS:
        (tmp_path / f"cerberus-{target}.tar.gz").write_bytes(b"archive")
    manifest = json.loads(create(tmp_path, "v0.4.0").read_text())
    assert set(manifest["builds"]) == launcher.TARGETS
    assert all(item["sha256"] == hashlib.sha256(b"archive").hexdigest() for item in manifest["builds"].values())


def test_launch_uses_installed_executable_and_separate_data(installer, monkeypatch, tmp_path):
    data = archive_bytes()
    serve(monkeypatch, data)
    state = installer.install(build_for(data))
    private = tmp_path / "private-data"
    monkeypatch.setenv("CERBERUS_DATA", str(private))
    calls = []
    class Child:
        def poll(self):
            return None
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda args, **kw: calls.append((args, kw)) or Child())
    installer.launch()
    args, options = calls[0]
    assert args == [str(launcher.executable_path(installer.installation_path(state), installer.target))]
    assert options["env"]["CERBERUS_DATA"] == str(private)
    assert not options.get("shell")
    assert options["stdout"].closed


def test_linux_shortcut_quotes_executable_paths_without_shell_execution(tmp_path, monkeypatch):
    from launcher import shortcuts
    source = tmp_path / 'download' / 'CerberusLauncher'
    source.parent.mkdir()
    source.write_bytes(b"launcher")
    root = tmp_path / 'my apps $test'
    root.mkdir()
    monkeypatch.setattr(shortcuts.sys, "frozen", True, raising=False)
    monkeypatch.setattr(shortcuts.sys, "platform", "linux")
    monkeypatch.setattr(shortcuts.sys, "executable", str(source))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "menu"))
    shortcuts.register(root)
    entry = tmp_path / "menu/applications/cerberus-launcher.desktop"
    text = entry.read_text()
    assert 'Exec="' in text and r'\$test' in text
    assert "Name=Cerberus\n" in text
    assert (root / "CerberusLauncher").read_bytes() == b"launcher"
    shortcuts.unregister(root)
    assert not entry.exists() and not (root / "CerberusLauncher").exists()


def test_windows_shortcut_passes_paths_as_environment_data(tmp_path, monkeypatch):
    from launcher import shortcuts
    source = tmp_path / 'download.exe'
    source.write_bytes(b"launcher")
    root = tmp_path / "folder with 'quotes'"
    root.mkdir()
    monkeypatch.setattr(shortcuts.sys, "frozen", True, raising=False)
    monkeypatch.setattr(shortcuts.sys, "platform", "win32")
    monkeypatch.setattr(shortcuts.sys, "executable", str(source))
    calls = []
    monkeypatch.setattr(shortcuts.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)))
    shortcuts.register(root)
    args, options = calls[0]
    assert str(root) not in args[-1]
    assert options["env"]["CERBERUS_LAUNCHER_EXE"] == str(root / "CerberusLauncher.exe")


def test_macos_launcher_is_copied_as_a_complete_app_bundle(tmp_path, monkeypatch):
    from launcher import shortcuts
    source = tmp_path / "Downloads/CerberusLauncher.app/Contents/MacOS/CerberusLauncher"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"launcher")
    monkeypatch.setattr(shortcuts.sys, "frozen", True, raising=False)
    monkeypatch.setattr(shortcuts.sys, "platform", "darwin")
    monkeypatch.setattr(shortcuts.sys, "executable", str(source))
    monkeypatch.setattr(shortcuts.Path, "home", lambda: tmp_path / "home")
    shortcuts.register(tmp_path / "installation")
    assert (tmp_path / "home/Applications/Cerberus.app/Contents/MacOS/CerberusLauncher").read_bytes() == b"launcher"


@pytest.mark.parametrize("latest,installed,newer", [
    ("v0.5.0", "v0.4.0", True), ("v0.5.0", "v0.5.0", False),
    ("v0.4.0", "v0.5.0", False), ("v0.10.0", "v0.9.0", True),
])
def test_update_comparison_uses_numeric_versions(latest, installed, newer):
    from launcher.presentation import is_newer
    assert is_newer(latest, installed) is newer


def test_chosen_folder_never_mixes_cerberus_with_other_files(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert launcher.root_in(empty) == empty
    busy = tmp_path / "Documents"
    busy.mkdir()
    (busy / "notes.txt").write_text("mine")
    assert launcher.root_in(busy) == busy / "Cerberus"
    existing = tmp_path / "Apps"
    existing.mkdir()
    (existing / "installation.json").write_text("{}")
    assert launcher.root_in(existing) == existing


def test_chosen_install_folder_is_remembered(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    assert launcher.saved_root() == launcher.install_directory()
    launcher.save_root(tmp_path / "Programs" / "Cerberus")
    assert launcher.saved_root() == tmp_path / "Programs" / "Cerberus"
    launcher.forget_root()
    assert launcher.saved_root() == launcher.install_directory()


@pytest.mark.parametrize("target", ["linux-x86_64", "macos-arm64"])
def test_installed_app_finds_its_install_folder(installer, monkeypatch, target):
    data = archive_bytes(target=target)
    serve(monkeypatch, data)
    installer.target = target
    state = installer.install(build_for(data, target=target))
    executable = launcher.executable_path(installer.installation_path(state), target)
    assert launcher.installed_root(executable, target) == installer.root
    assert launcher.installed_root(installer.root / "elsewhere" / "Cerberus", target) is None


def test_running_app_updates_itself_and_keeps_only_its_own_version(installer, monkeypatch):
    first, second, third = (archive_bytes(content=bytes([n])) for n in range(3))
    serve(monkeypatch, first)
    installer.install(build_for(first))
    serve(monkeypatch, second)
    running = installer.install(build_for(second, "v0.5.0"))
    monkeypatch.setattr(installer, "running", lambda: True)
    serve(monkeypatch, third)
    new = installer.install(build_for(third, "v0.6.0"), from_app=True)
    assert installer.state() == new
    names = {path.name for path in (installer.root / "versions").iterdir()}
    assert names == {installer.installation_path(running).name, installer.installation_path(new).name}


def test_update_never_removes_the_running_version(installer, monkeypatch):
    first, second, third = (archive_bytes(content=bytes([n])) for n in range(3))
    serve(monkeypatch, first)
    running = installer.install(build_for(first))
    serve(monkeypatch, second)
    installer.install(build_for(second, "v0.5.0"))  # downloaded, not restarted yet
    executable = launcher.executable_path(installer.installation_path(running), installer.target)
    monkeypatch.setattr(launcher.sys, "executable", str(executable))
    serve(monkeypatch, third)
    installer.install(build_for(third, "v0.6.0"), from_app=True)
    assert executable.is_file()


def test_frozen_children_start_as_independent_programs(monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/local/lib")
    env = launcher.child_environment({"CERBERUS_DATA": "/data"})
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert env["LD_LIBRARY_PATH"] == "/usr/local/lib"
    assert env["CERBERUS_DATA"] == "/data"


def test_source_checkout_does_not_offer_in_app_updates():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    info = client.get("/updates").json()
    assert info["managed"] is False
    assert client.post("/updates/download").status_code == 409
    assert client.post("/updates/restart").status_code == 409
    assert client.post("/updates/uninstall").status_code == 409


def test_platform_labels_match_every_launcher_build():
    from launcher.presentation import PLATFORM_LABELS
    assert set(PLATFORM_LABELS) == launcher.TARGETS


@pytest.mark.parametrize("path", ["README.md", "site/index.html"])
def test_public_installation_uses_terminal_instead_of_launcher(path):
    text = Path(path).read_text(encoding="utf-8")
    assert "git clone https://github.com/23lambi/Cerberus-ai.git" in text
    assert "venv/bin/python -m pip install -r requirements.txt" in text
    assert r".\venv\Scripts\python.exe -m pip install -r requirements.txt" in text
    assert "venv/bin/python desktop.py" in text
    assert r".\venv\Scripts\python.exe desktop.py" in text
    assert "cerberus-launcher-" not in text


def test_certificates_are_found_outside_the_build_machines_folder(tmp_path, monkeypatch):
    import ssl
    import certifi
    monkeypatch.setattr(launcher.ssl, "create_default_context", lambda: ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    context = launcher.tls_context([str(tmp_path / "missing.pem"), certifi.where()])
    assert context.cert_store_stats()["x509_ca"] > 0


def test_release_check_fails_when_https_cannot_be_verified(monkeypatch, capsys):
    import ssl
    empty = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # no certificates at all, like the old bug
    monkeypatch.setattr(launcher, "tls_context", lambda: empty)
    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda request, timeout, context: (_ for _ in ()).throw(
        ssl.SSLCertVerificationError("certificate verify failed")))
    assert launcher.check_release() == 1
    assert "Release check failed" in capsys.readouterr().err


def test_ci_token_is_only_sent_to_the_github_api(monkeypatch):
    monkeypatch.setenv("CERBERUS_GITHUB_TOKEN", "secret")
    sent = {}
    monkeypatch.setattr(launcher.urllib.request, "urlopen",
                        lambda request, timeout, context: sent.update({request.full_url: request.get_header("Authorization")}))
    launcher.open_url("https://api.github.com/repos/23lambi/Cerberus-ai/releases/latest")
    launcher.open_url("https://github.com/23lambi/Cerberus-ai/releases/download/v0.5.0/release-manifest.json")
    assert sent == {"https://api.github.com/repos/23lambi/Cerberus-ai/releases/latest": "Bearer secret",
                    "https://github.com/23lambi/Cerberus-ai/releases/download/v0.5.0/release-manifest.json": None}


def test_whats_new_is_taken_from_the_release_notes():
    notes = "# Cerberus desktop\r\n\r\n## What's new\r\n\r\n- Mascot\r\n- Updates in the app\r\n\r\n## Install\r\n\r\n1. Download"
    assert launcher.whats_new(notes) == "- Mascot\n- Updates in the app"
    assert launcher.whats_new("## Install\n\n1. Download") == ""
    assert launcher.whats_new(None) == ""


def test_release_check_passes_when_github_answers_without_releases(monkeypatch, capsys):
    import urllib.error
    def not_found(request, timeout, context):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
    monkeypatch.setattr(launcher.urllib.request, "urlopen", not_found)
    assert launcher.check_release() == 0  # connected: the SSL part works
    assert "no release is published yet" in capsys.readouterr().out
    with pytest.raises(launcher.NoRelease):
        launcher.latest_release("linux-x86_64")
