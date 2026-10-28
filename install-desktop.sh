#!/bin/sh
# Puts Cerberus in your app menu, with its icon. Run it once:
#   sh install-desktop.sh
# Remove it again with:
#   rm ~/.local/share/applications/cerberus.desktop
#
# A .desktop file is how Linux desktops list programs: a name, an icon,
# and the command to run. Files in ~/.local/share/applications are only
# for you, so no sudo is needed.

set -e  # stop at the first error
HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET="$HOME/.local/share/applications/cerberus.desktop"
mkdir -p "$(dirname "$TARGET")"

cat > "$TARGET" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Cerberus
Comment=Your private AI, on this computer
Exec=$HERE/venv/bin/python $HERE/desktop.py
Icon=$HERE/static/cerberus.svg
Terminal=false
Categories=Utility;
StartupWMClass=cerberus
DESKTOP

echo "Installed: $TARGET"
echo "Cerberus is now in your app menu."
