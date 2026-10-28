"""Create the launcher's manifest only after all platform builds succeed."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launcher.manager import TARGETS, VERSION  # noqa: E402


def create(folder, version):
    if not VERSION.fullmatch(version):
        raise ValueError("Invalid release version")
    builds = {}
    for target in sorted(TARGETS):
        name = f"cerberus-{target}.tar.gz"
        path = folder / name
        if not path.is_file():
            raise ValueError(f"Missing platform build: {name}")
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        builds[target] = {"file": name, "size": path.stat().st_size, "sha256": digest}
    path = folder / "release-manifest.json"
    path.write_text(json.dumps({"version": version, "builds": builds}, indent=2) + "\n")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    print(create(args.folder, args.version))
