"""Exercise the real release archive through the installer, without a GUI."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launcher import manager  # noqa: E402


def check(archive, version):
    archive = archive.resolve()
    target = manager.target_name()
    with archive.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    with tempfile.TemporaryDirectory(prefix="cerberus-install-smoke-") as folder:
        root = Path(folder)
        installer = manager.Manager(root / "installation", target)
        # Only the locally built, checksummed archive is served in this smoke test.
        manager.open_url = lambda *a, **kw: archive.open("rb")
        installer.running = lambda: False
        build = {"version": version, "target": target, "url": "local-smoke-test", "sha256": digest, "size": archive.stat().st_size}
        state = installer.install(build)
        executable = manager.executable_path(installer.installation_path(state), target)
        report = root / "report.json"
        data = root / "personal-data"
        env = {**os.environ, "CERBERUS_DATA": str(data), "XDG_DATA_HOME": str(root / "system"),
               "CERBERUS_SMOKE_REPORT": str(report)}
        subprocess.run([str(executable), "--smoke-test"], env=env, timeout=120, check=True)
        assert json.loads(report.read_text())["static"]
        database = data / "cerberus.db"
        before = database.read_bytes()
        installer.uninstall()
        assert database.read_bytes() == before
        assert installer.state() is None
    print("Release archive installed, started, and uninstalled; personal data preserved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    check(args.archive, args.version)
