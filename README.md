<img src="static/cerberus.svg" alt="Cerberus logo" width="48" align="right">

# Cerberus

A desktop workspace for chat, documents, and research with local or cloud AI.

[![Checks](https://github.com/23lambi/Cerberus-ai/actions/workflows/checks.yml/badge.svg)](https://github.com/23lambi/Cerberus-ai/actions/workflows/checks.yml)
[![MIT license](https://img.shields.io/badge/license-MIT-737373)](LICENSE)

[Downloads](#download) · [Features](#features) · [User guide](docs/guide.md) · [Report a bug](https://github.com/23lambi/Cerberus-ai/issues/new/choose)

## Download

**First desktop release in preparation.** Downloads will appear after the
cross-platform builds pass and a stable release is published.

[![Windows x64](https://img.shields.io/badge/Windows-x64-24292f?style=for-the-badge)](https://github.com/23lambi/Cerberus-ai/releases)
[![macOS](https://img.shields.io/badge/macOS-Apple_Silicon_%26_Intel-24292f?style=for-the-badge)](https://github.com/23lambi/Cerberus-ai/releases)
[![Linux x64](https://img.shields.io/badge/Linux-x64-24292f?style=for-the-badge)](https://github.com/23lambi/Cerberus-ai/releases)

The Releases page will list each platform’s launcher ZIP once the first release is published.
[Build status](https://github.com/23lambi/Cerberus-ai/actions/workflows/release.yml) · [Platform requirements](docs/launcher.md#supported-builds)

Once a release is available:

1. Download your launcher ZIP and extract it.
2. Open the launcher → **Install Cerberus** → **Open Cerberus**.
3. Choose your AI engine and model in **Settings → Setup check**.

**No Python or Git setup is needed for packaged downloads.** The launcher
handles app updates and repairs; your chats and settings are stored separately.
Initial builds are unsigned.

<details>
<summary>Which download should I choose?</summary>

| Your computer | Release file | Open |
| --- | --- | --- |
| Windows · 64-bit | `cerberus-launcher-windows-x86_64.zip` | `CerberusLauncher.exe` |
| macOS · Apple Silicon | `cerberus-launcher-macos-arm64.zip` | `CerberusLauncher.app` |
| macOS · Intel | `cerberus-launcher-macos-x86_64.zip` | `CerberusLauncher.app` |
| Linux · 64-bit | `cerberus-launcher-linux-x86_64.zip` | `CerberusLauncher` |

</details>

<p align="center">
  <img src="docs/assets/chat.png" alt="Cerberus desktop chat with connection status, prompt suggestions, and a compact message composer" width="100%">
</p>
<p align="center"><sub>Chat interface shown with sample data.</sub></p>

## Features

- **Chat & reasoning** — streaming answers, Deep think, images, and tools.
- **Documents & projects** — searchable files, Markdown editing, version history,
  and AI edits you review before applying.
- **Memory** — saved facts available across your chats.
- **Research** — web sources and reports with numbered citations.
- **Data control** — local storage, full backups, and Markdown or JSON exports.

## AI engines

| On your computer | Cloud services |
| --- | --- |
| Ollama · llama.cpp · LM Studio · Jan | Hugging Face · OpenAI · Groq · OpenRouter |

Other OpenAI-compatible servers are supported too. Model support for images
and tools varies by engine and model.

**Models → Your models** manages your Ollama collection. **Find models** lets
you browse downloads or discover running **Local apps**, then choose **Use in chat**.

Cerberus can install its own Ollama or start an installed llama.cpp server with
a GGUF file. Web search and Research use an optional SearXNG server.
[Setup details →](docs/guide.md#choosing-an-ai-engine)

## Privacy

Chats and documents are stored locally. Cloud engines receive your messages
and supplied context; web features contact search services and websites.
API keys are stored separately from the database and excluded from backups.

## Development

Built with **FastAPI**, **SQLite**, **plain JavaScript**, and **pywebview**.

<details>
<summary>Run from source · Python 3.14</summary>

```bash
git clone https://github.com/23lambi/Cerberus-ai.git
cd Cerberus-ai
```

**Linux & macOS**

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
sh install-desktop.sh
```

**Windows · PowerShell**

```powershell
py -3.14 -m venv venv
venv\Scripts\pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File install-desktop.ps1
```

**Checks**

```bash
venv/bin/python -m pytest -q
node tests/frontend.test.cjs
```

</details>

[User guide](docs/guide.md) · [Contributing](CONTRIBUTING.md) · [Project layout](docs/development/architecture.md) · [Build releases](docs/releasing.md)

## Feedback & license

Found a bug or have an idea? [Open an issue](https://github.com/23lambi/Cerberus-ai/issues/new/choose).

[MIT licensed](LICENSE). Bundled libraries retain their [own licenses](static/vendor/README.md).
