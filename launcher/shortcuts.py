"""Install the frozen launcher in the user's own app menu, without admin rights.

The menu entry is called Cerberus: once the app is installed, the launcher
opens it straight away, so the entry keeps working after in-app updates
move the app to a new version folder.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path


def mac_bundle():
    return Path.home() / "Applications" / "Cerberus.app"


def windows_menu_folder():
    return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Cerberus"


def linux_entry():
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications" / "cerberus-launcher.desktop"


def launcher_executable(root, platform=None):
    """Where register() keeps the launcher copy that the menu entry starts."""
    platform = platform or sys.platform
    if platform == "darwin":
        return mac_bundle() / "Contents" / "MacOS" / "CerberusLauncher"
    return Path(root) / ("CerberusLauncher.exe" if platform == "win32" else "CerberusLauncher")


def register(root):
    if not getattr(sys, "frozen", False):
        return  # Source checkouts keep using the existing desktop install scripts.
    source = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        bundle = source.parents[2]
        destination = mac_bundle()
        if bundle != destination.resolve():
            if destination.exists():
                return  # Do not overwrite a launcher another window might be using.
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(bundle, destination, symlinks=True)
        return
    destination = launcher_executable(root)
    if source != destination.resolve():
        shutil.copy2(source, destination)
    resources = Path(__file__).resolve().parents[1]
    for name in ("LICENSE", "NOTICE"):
        if (resources / name).is_file():
            shutil.copy2(resources / name, root / name)
    if sys.platform == "win32":
        script = '''
$folder = $env:CERBERUS_MENU_FOLDER
New-Item -ItemType Directory -Force -Path $folder | Out-Null
Remove-Item -LiteralPath (Join-Path $folder 'Cerberus Launcher.lnk') -ErrorAction SilentlyContinue
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $folder 'Cerberus.lnk'))
$shortcut.TargetPath = $env:CERBERUS_LAUNCHER_EXE
$shortcut.WorkingDirectory = Split-Path $env:CERBERUS_LAUNCHER_EXE
$shortcut.IconLocation = $env:CERBERUS_LAUNCHER_EXE
$shortcut.Save()
'''
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       env={**os.environ, "CERBERUS_LAUNCHER_EXE": str(destination),
                            "CERBERUS_MENU_FOLDER": str(windows_menu_folder())},
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True, timeout=20)
        return
    destination.chmod(destination.stat().st_mode | 0o755)
    icon = resources / "cerberus.svg"
    if icon.is_file():
        shutil.copy2(icon, root / "cerberus.svg")
    entry = linux_entry()
    entry.parent.mkdir(parents=True, exist_ok=True)
    escaped = str(destination).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
    entry.write_text(
        '[Desktop Entry]\nType=Application\nName=Cerberus\nComment=Chat, documents and research with local or cloud AI\n'
        f'Exec="{escaped}"\nIcon={root / "cerberus.svg"}\nTerminal=false\nCategories=Utility;\n')


def unregister(root):
    """Remove the menu entry and the launcher copy made by register()."""
    if sys.platform == "darwin":
        bundle = mac_bundle()
        if (bundle / "Contents" / "MacOS" / "CerberusLauncher").is_file():
            shutil.rmtree(bundle, ignore_errors=True)
        return
    if sys.platform == "win32":
        folder = windows_menu_folder()
        for name in ("Cerberus.lnk", "Cerberus Launcher.lnk"):
            (folder / name).unlink(missing_ok=True)
        try:
            folder.rmdir()
        except OSError:
            pass
        return  # The running launcher.exe cannot delete itself on Windows.
    linux_entry().unlink(missing_ok=True)
    for name in ("CerberusLauncher", "cerberus.svg", "LICENSE", "NOTICE"):
        (Path(root) / name).unlink(missing_ok=True)
