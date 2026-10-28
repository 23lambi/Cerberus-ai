# Puts Cerberus in the Windows Start menu, with its icon. Run it once in
# PowerShell, from the Cerberus folder:
#   powershell -ExecutionPolicy Bypass -File install-desktop.ps1
# (-ExecutionPolicy Bypass: Windows blocks scripts by default; this lets
#  only this one run, this one time.)
#
# Remove it again by deleting "Cerberus" from:
#   %APPDATA%\Microsoft\Windows\Start Menu\Programs

$ErrorActionPreference = "Stop"  # stop at the first error
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

# pythonw.exe is the Python that opens no black console window next to the app.
$Python = Join-Path $Here "venv\Scripts\pythonw.exe"
if (-not (Test-Path $Python)) {
    Write-Host "No venv found. First run: py -m venv venv; venv\Scripts\pip install -r requirements.txt"
    exit 1
}

# A Start-menu entry is a shortcut (.lnk) in the user's own Programs folder.
# WScript.Shell is the part of Windows that knows how to write shortcuts.
$Programs = [Environment]::GetFolderPath("Programs")
$Shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $Programs "Cerberus.lnk"))
$Shortcut.TargetPath = $Python
$Shortcut.Arguments = '"' + (Join-Path $Here "desktop.py") + '"'
$Shortcut.WorkingDirectory = $Here
$Shortcut.IconLocation = Join-Path $Here "static\cerberus.ico"
$Shortcut.Description = "Your private AI, on this computer"
$Shortcut.Save()

Write-Host "Installed: $(Join-Path $Programs 'Cerberus.lnk')"
Write-Host "Cerberus is now in the Start menu."
