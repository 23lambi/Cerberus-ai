# Cerberus Launcher

[← README](../README.md)

The launcher installs and updates Cerberus from this repository's published
GitHub releases. The launcher and application include their Python runtimes;
users do not install Python, Git, or pip.

Downloads become available when a stable release is published. Draft releases
and build artifacts do not appear in the launcher's download list.

## Using the launcher

1. Download the launcher ZIP for your computer from
   [Releases](https://github.com/23lambi/Cerberus-ai/releases).
2. Extract it. Open `CerberusLauncher.exe` on Windows, `CerberusLauncher.app`
   on macOS, or `CerberusLauncher` on Linux.
3. Choose **Install Cerberus**, wait for verification, then choose **Open Cerberus**.
4. After installation, **Cerberus Launcher** is also available in your app menu
   (Start menu on Windows, `~/Applications` on macOS).
5. In Cerberus, open **Settings → Setup check** to choose an AI engine and model.

**Check updates** checks the latest stable release. **Update** installs a newer
application. **Repair** downloads the latest release again. **Uninstall app**
removes installed application versions while preserving chats, keys, settings,
and separately installed AI engines/models. The extracted launcher remains available, and the installed menu shortcut uses
its own copy of the launcher.

Close Cerberus before updating, repairing, or uninstalling. A cancelled or
failed download leaves the current installation selected. Previous versions
remain on disk until uninstall, allowing manual recovery if needed.

The launcher chooses the correct app package automatically. **Help** opens this
guide. An installed app can still be opened when the update server is unavailable.

## Supported builds

| Download target | Platform |
| --- | --- |
| `linux-x86_64` | Linux x64; CI builds on Ubuntu 24.04 |
| `windows-x86_64` | Windows x64 with WebView2 Runtime |
| `macos-arm64` | Apple Silicon Mac; CI builds on macOS 15 |
| `macos-x86_64` | Intel Mac; CI builds on macOS 15 |

Linux requires a desktop session and compatible system graphics libraries.
Release builds include the PySide6 Qt web engine, with shared libraries kept
as separate files. Windows uses WebView2; macOS uses system WebKit. Initial
releases target the OS versions above; compatibility with older systems needs
separate testing.

The initial packaging is unsigned. Windows may show a SmartScreen warning;
macOS distribution still needs Developer ID signing and notarization for a
smooth public download experience. Signing credentials are not included in
this repository. Do not present an unsigned test build as signed or notarized.

## Where files go

| Platform | Downloaded application versions | Personal application data |
| --- | --- | --- |
| Linux | `~/.local/share/cerberus-launcher/versions` | `~/.local/share/cerberus` |
| macOS | `~/Library/Application Support/CerberusLauncher/versions` | `~/Library/Application Support/Cerberus` |
| Windows | `%LOCALAPPDATA%/CerberusLauncher/versions` | `%LOCALAPPDATA%/Cerberus` |

`XDG_DATA_HOME` changes the Linux base folder. `CERBERUS_DATA` still overrides
personal application storage. Existing source-checkout databases stay in their
original folders; set `CERBERUS_DATA` to that folder to use one with a packaged
app, or follow the [backup/restore guide](guide.md#backup-and-export).

The launcher stores only installation metadata and app logs in its own folder.
It never packages your development database or uploads chats. Release checks
and downloads contact GitHub. Models and external engines are set up separately
inside Cerberus. The launcher does not automatically update itself in this version.

## Build and publish

Build on each target OS. PyInstaller does not cross-compile desktop apps.

```bash
python -m pip install -r packaging/requirements-app.txt
python scripts/build_release.py launcher --version v0.4.0
python scripts/build_release.py app --version v0.4.0
```

Linux build machines need Tk 8.6 development/runtime libraries. macOS and Windows
Python distributions must include Tcl/Tk. To run the launcher from source:

```bash
python -m launcher
```

The **Build desktop releases** workflow can be run manually to produce test
artifacts. A version tag such as `v0.4.0` builds all four targets, runs tests,
smoke-tests the bundled executables and installer, creates checksums, and opens
a **draft** GitHub release. Review each platform, signing, license notices, and
release notes before publishing the draft. The launcher only sees published,
stable releases.

The app assets are `cerberus-<target>.tar.gz`. Each launcher ZIP is
`cerberus-launcher-<target>.zip`. `release-manifest.json` records the version,
size, and SHA-256 checksum of all four application downloads. Installation
verifies both size and checksum before unpacking. Archives are extracted into
staging with path/link checks; an atomic installation record switches the
selected version only after extraction succeeds.

The bundled GUI libraries, Python runtime, and other dependencies retain their
own licenses. Project-owned launcher and application code remains MIT licensed.
