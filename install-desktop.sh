#!/bin/sh
# Puts Cerberus in your app menu, with its icon. Run it once:
#   sh install-desktop.sh
# Linux and macOS. On Windows, use install-desktop.ps1 instead.
#
# Remove it again with:
#   Linux: rm ~/.local/share/applications/cerberus.desktop
#   macOS: rm -r ~/Applications/Cerberus.app
#
# Both places are only for you, so no sudo is needed.

set -e  # stop at the first error
HERE="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$HERE/venv/bin/python"

if [ ! -x "$PYTHON" ]; then
    echo "No venv found. First run: python3 -m venv venv && venv/bin/pip install -r requirements.txt"
    exit 1
fi

if [ "$(uname)" = "Darwin" ]; then
    # macOS: an app is a folder ending in .app with a fixed layout:
    #   Contents/Info.plist        what the app is called, its icon...
    #   Contents/MacOS/Cerberus    the program to start (here: a small script)
    #   Contents/Resources/        the icon, in Apple's .icns format
    APP="$HOME/Applications/Cerberus.app"
    mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

    cat > "$APP/Contents/MacOS/Cerberus" <<SCRIPT
#!/bin/sh
exec "$PYTHON" "$HERE/desktop.py"
SCRIPT
    chmod +x "$APP/Contents/MacOS/Cerberus"

    # macOS's own tools turn the PNG into an .icns: sips makes each size,
    # iconutil packs them into one file.
    ICONSET="$(mktemp -d)/cerberus.iconset"
    mkdir -p "$ICONSET"
    for size in 16 32 128 256 512; do
        sips -z $size $size "$HERE/static/cerberus.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
        double=$((size * 2))
        sips -z $double $double "$HERE/static/cerberus.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
    done
    iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/cerberus.icns"

    cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Cerberus</string>
    <key>CFBundleDisplayName</key><string>Cerberus</string>
    <key>CFBundleIdentifier</key><string>local.cerberus</string>
    <key>CFBundleExecutable</key><string>Cerberus</string>
    <key>CFBundleIconFile</key><string>cerberus</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleVersion</key><string>0.3.0</string>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

    echo "Installed: $APP"
    echo "Cerberus is now in Launchpad and in Finder > Applications (your own)."
    exit 0
fi

# Linux: a .desktop file is how Linux desktops list programs: a name, an
# icon, and the command to run.
TARGET="$HOME/.local/share/applications/cerberus.desktop"
mkdir -p "$(dirname "$TARGET")"

cat > "$TARGET" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Cerberus
Comment=Your private AI, on this computer
Exec=$PYTHON $HERE/desktop.py
Icon=$HERE/static/cerberus.svg
Terminal=false
Categories=Utility;
StartupWMClass=cerberus
DESKTOP

echo "Installed: $TARGET"
echo "Cerberus is now in your app menu."
