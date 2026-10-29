# Cerberus Launcher

[← README](../README.md)

> **Experimental:** the launcher is not ready for general use. Install Cerberus
> with the [terminal commands in the README](../README.md#download). The notes
> below are retained for launcher development and testing.

The launcher installs Cerberus once. After that, Cerberus updates itself from
**Settings → Updates**. The launcher and application include their Python
runtimes; users do not install Python, Git, or pip.

Downloads become available when a stable release is published. Draft releases
and build artifacts are never offered.

## Using the launcher

1. Download the launcher ZIP for your computer from
   [Releases](https://github.com/23lambi/Cerberus-ai/releases).
2. Extract it. Open `CerberusLauncher.exe` on Windows, `CerberusLauncher.app`
   on macOS, or `CerberusLauncher` on Linux.
3. Optional: choose **Change…** to install somewhere else. An empty folder is
   used as is; any other folder gets its own `Cerberus` subfolder.
4. Choose **Install Cerberus**. When the download is verified, the launcher
   opens Cerberus and closes itself.
5. In Cerberus, open **Settings → Setup check** to choose an AI engine and model.

A **Cerberus** entry is added to your app menu (Start menu on Windows,
`~/Applications` on macOS). It opens the installed app directly. Opening the
downloaded launcher again does the same, so you can delete the download.

## Updates and uninstall

Cerberus checks GitHub for a new version shortly after it starts. When one is
available, a dot appears on **Settings**. Open **Settings → Updates**, choose
**Download update**, then **Restart now**. The new version is downloaded and
verified next to the running one, so a failed or cancelled download changes
nothing. One previous version is kept until the next update.

**Settings → Updates → Uninstall Cerberus…** closes the app and removes it and
its menu entry. Chats, keys, settings, and separately installed AI engines or
models are kept. If the installation is damaged, opening the launcher offers to
install again; your data is kept.

### First start of an unsigned build

The launcher is not yet signed by a verified developer, so your system asks
once before opening it:

- **Windows:** on "Windows protected your PC", choose **More info → Run anyway**.
- **macOS:** open `CerberusLauncher.app`; when macOS says it cannot verify it,
  choose **Done**, then open **System Settings → Privacy & Security** and choose
  **Open Anyway** next to CerberusLauncher.
- **Linux:** if double-clicking does nothing, run `chmod +x CerberusLauncher`
  in the extracted folder, then open it again.

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

The initial packaging is unsigned. Windows shows a SmartScreen warning and
macOS a Gatekeeper warning; see [First start](#first-start-of-an-unsigned-build).
macOS distribution still needs Developer ID signing and notarization for a
smooth public download experience. Signing credentials are not included in
this repository. Do not present an unsigned test build as signed or notarized.

## Where files go

| Platform | Default install folder | Personal application data |
| --- | --- | --- |
| Linux | `~/.local/share/cerberus-launcher` | `~/.local/share/cerberus` |
| macOS | `~/Library/Application Support/CerberusLauncher` | `~/Library/Application Support/Cerberus` |
| Windows | `%LOCALAPPDATA%/CerberusLauncher` | `%LOCALAPPDATA%/Cerberus` |

Application versions are in the install folder's `versions` subfolder. A
custom install folder is remembered in `location.json` in the default folder.
Personal data always stays in the data folder, wherever the app is installed.

`XDG_DATA_HOME` changes the Linux base folder. `CERBERUS_DATA` still overrides
personal application storage. Existing source-checkout databases stay in their
original folders; set `CERBERUS_DATA` to that folder to use one with a packaged
app, or follow the [backup/restore guide](guide.md#backup-and-export).

The launcher stores only installation metadata and app logs in its own folder.
It never packages your development database or uploads chats. Release checks
and downloads contact GitHub. Models and external engines are set up separately
inside Cerberus. The menu entry keeps the launcher version it was installed with;
it only opens the app, so it does not need updates.

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

Use **Actions → Build desktop releases → Run workflow**, enter a version, and
leave **Create a draft release** enabled. All four builds must pass before a
draft is created. Disable that option to build test artifacts only. Version-tag
pushes also create a draft after passing the builds.

Review the draft and test each platform before publishing. The launcher only
sees published, stable releases in a **public repository**; it does not use your
GitHub login or access private releases. See [Publishing a release](releasing.md)
for the complete maintainer steps.

The app assets are `cerberus-<target>.tar.gz`. Each launcher ZIP is
`cerberus-launcher-<target>.zip`. `release-manifest.json` records the version,
size, and SHA-256 checksum of all four application downloads. Installation
verifies both size and checksum before unpacking. Archives are extracted into
staging with path/link checks; an atomic installation record switches the
selected version only after extraction succeeds.

The bundled GUI libraries, Python runtime, and other dependencies retain their
own licenses. Project-owned launcher and application code is licensed under Apache 2.0.
