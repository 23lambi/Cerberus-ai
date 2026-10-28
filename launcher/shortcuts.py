"""Install the frozen launcher in the user's own app menu, without admin rights."""
import os
import shutil
import subprocess
import sys
from pathlib import Path


def register(root):
    if not getattr(sys, "frozen", False):
        return  # Source checkouts keep using the existing desktop install scripts.
    source = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        bundle = source.parents[2]
        destination = Path.home() / "Applications" / "CerberusLauncher.app"
        if bundle != destination.resolve():
            if destination.exists():
                return  # Do not overwrite a launcher another window might be using.
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(bundle, destination, symlinks=True)
        return
    destination = root / ("CerberusLauncher.exe" if sys.platform == "win32" else "CerberusLauncher")
    if source != destination.resolve():
        shutil.copy2(source, destination)
    resources = Path(__file__).resolve().parents[1]
    for name in ("LICENSE", "NOTICE"):
        if (resources / name).is_file():
            shutil.copy2(resources / name, root / name)
    if sys.platform == "win32":
        script = '''
$folder = Join-Path ([Environment]::GetFolderPath('Programs')) 'Cerberus'
New-Item -ItemType Directory -Force -Path $folder | Out-Null
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $folder 'Cerberus Launcher.lnk'))
$shortcut.TargetPath = $env:CERBERUS_LAUNCHER_EXE
$shortcut.WorkingDirectory = Split-Path $env:CERBERUS_LAUNCHER_EXE
$shortcut.IconLocation = $env:CERBERUS_LAUNCHER_EXE
$shortcut.Save()
'''
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       env={**os.environ, "CERBERUS_LAUNCHER_EXE": str(destination)},
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True, timeout=20)
        return
    destination.chmod(destination.stat().st_mode | 0o755)
    icon = Path(__file__).resolve().parents[1] / "cerberus.svg"
    if icon.is_file():
        shutil.copy2(icon, root / "cerberus.svg")
    applications = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"
    applications.mkdir(parents=True, exist_ok=True)
    escaped = str(destination).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
    (applications / "cerberus-launcher.desktop").write_text(
        '[Desktop Entry]\nType=Application\nName=Cerberus Launcher\n'
        f'Exec="{escaped}"\nIcon={root / "cerberus.svg"}\nTerminal=false\nCategories=Utility;\n')
