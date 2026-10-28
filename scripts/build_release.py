"""Build on the destination OS: Python scripts cannot cross-compile GUI apps."""
import argparse
import json
import importlib.metadata
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from launcher.manager import VERSION, executable_path, target_name  # noqa: E402


def runtime_notices(work):
    notices = work / "notices"
    notices.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "packaging/licenses", notices / "licenses", dirs_exist_ok=True)
    shutil.copy2(ROOT / "packaging/THIRD-PARTY-NOTICES.md", notices / "THIRD-PARTY-NOTICES.md")
    versions = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name", "unknown")
        versions[name] = distribution.version
        for entry in distribution.files or []:
            parts = entry.parts
            if not any(part.endswith(".dist-info") for part in parts):
                continue
            if not any(word in str(entry).lower() for word in ("license", "copying", "notice")):
                continue
            source = Path(distribution.locate_file(entry))
            if not source.is_file():
                continue
            # RECORD paths are untrusted metadata; keep copies beneath a simple package name.
            safe_name = "".join(char for char in name if char.isalnum() or char in "-_.")
            index = next(index for index, part in enumerate(parts) if part.endswith(".dist-info"))
            relative = Path(*parts[index + 1:])
            destination = notices / "dependency-licenses" / safe_name / relative
            if not destination.resolve().is_relative_to(notices.resolve()):
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    (notices / "runtime-info.json").write_text(json.dumps({"python": sys.version, "distributions": versions}, indent=2))
    return notices


def build(component, version):
    import PyInstaller.__main__

    if component == "launcher":
        # Detect missing native Tk dependencies before producing an unusable binary.
        import tkinter
        tkinter.Tcl()
    target = target_name()
    name = "Cerberus" if component == "app" else "CerberusLauncher"
    work = ROOT / "build" / component
    dist = ROOT / "dist" / component
    work.mkdir(parents=True, exist_ok=True)
    args = [str(ROOT / "packaging" / (component + "_entry.py")), "--name", name,
            "--paths", str(ROOT), "--distpath", str(dist), "--workpath", str(work / "work"),
            "--specpath", str(work), "--noconfirm", "--windowed", "--noupx"]
    if component == "launcher":
        args += ["--add-data", f"{ROOT / 'static/cerberus.svg'}:."]
    if component == "launcher" and sys.platform != "darwin":
        args += ["--onefile"]
    else:
        args += ["--onedir"]
    if sys.platform == "win32":
        args += ["--icon", str(ROOT / "static/cerberus.ico")]
    if sys.platform == "darwin":
        args += ["--osx-bundle-identifier", "io.github.23lambi." + name.lower()]
    if component == "app":
        version_file = work / "release-version.txt"
        version_file.write_text(version)
        args += ["--add-data", f"{ROOT / 'static'}:static", "--add-data", f"{ROOT / 'LICENSE'}:.",
                 "--add-data", f"{version_file}:.", "--collect-all", "capstone", "--collect-all", "webview", "--collect-submodules", "uvicorn"]
        if sys.platform.startswith("linux"):
            os.environ["QT_API"] = "pyside6"
            args += ["--hidden-import", "webview.platforms.qt", "--hidden-import", "PySide6.QtWebEngineWidgets",
                     "--exclude-module", "PyQt6", "--exclude-module", "PyQt5", "--exclude-module", "PySide2"]
        elif sys.platform == "darwin":
            args += ["--hidden-import", "webview.platforms.cocoa"]
        else:
            args += ["--hidden-import", "webview.platforms.winforms"]
    PyInstaller.__main__.run(args)
    output = dist / (name + ".app" if sys.platform == "darwin" else name)
    if component == "launcher" and sys.platform == "win32":
        output = dist / (name + ".exe")
    if not output.exists():
        raise RuntimeError(f"Build output missing: {output}")

    # Test the actual executable and bundled resources without opening a window.
    if component == "app":
        executable = executable_path(dist, target)
    elif sys.platform == "darwin":
        executable = output / "Contents/MacOS" / name
    else:
        executable = output
    with tempfile.TemporaryDirectory(prefix="cerberus-package-smoke-") as temp:
        report = Path(temp) / "report.json"
        env = {**os.environ, "CERBERUS_DATA": str(Path(temp) / "data"),
               "XDG_DATA_HOME": str(Path(temp) / "system"), "CERBERUS_SMOKE_REPORT": str(report)}
        subprocess.run([str(executable), "--smoke-test"], env=env, check=True, timeout=120)
        result = json.loads(report.read_text())
        assert result.get("launcher") if component == "launcher" else result.get("static") and result["routes"] > 0

    release = ROOT / "dist" / "release"
    release.mkdir(parents=True, exist_ok=True)
    notices = runtime_notices(work)
    if component == "app":
        archive = release / f"cerberus-{target}.tar.gz"
        with tarfile.open(archive, "w:gz", dereference=False) as tar:
            tar.add(output, arcname=output.name)
            tar.add(ROOT / "LICENSE", arcname="LICENSE")
            for item in notices.iterdir():
                tar.add(item, arcname=item.name)
        # Record installed distribution licenses beside the downloadable app.
        shutil.copy2(ROOT / "LICENSE", release / "LICENSE.txt")
    else:
        archive = release / f"cerberus-launcher-{target}.zip"
        if sys.platform == "darwin":
            # ditto preserves symlinks and metadata in .app bundles.
            with tempfile.TemporaryDirectory(dir=work) as staging:
                stage = Path(staging)
                shutil.copytree(output, stage / output.name, symlinks=True)
                shutil.copytree(notices, stage / "runtime-notices")
                shutil.copy2(ROOT / "LICENSE", stage / "LICENSE.txt")
                subprocess.run(["ditto", "-c", "-k", str(stage), str(archive)], check=True)
        else:
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
                zipped.write(output, arcname=output.name)
                zipped.write(ROOT / "LICENSE", arcname="LICENSE.txt")
                for item in notices.rglob("*"):
                    if item.is_file():
                        zipped.write(item, arcname="runtime-notices/" + str(item.relative_to(notices)))
    print("Built and smoke-tested:", archive)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("component", choices=["app", "launcher"])
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    if not VERSION.fullmatch(args.version):
        parser.error("Use a release version such as v0.4.0")
    os.environ.setdefault("PYINSTALLER_CONFIG_DIR", str(ROOT / "build" / "pyinstaller-cache"))
    os.chdir(ROOT)
    build(args.component, args.version)


if __name__ == "__main__":
    main()
