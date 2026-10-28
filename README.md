<img src="static/cerberus.svg" alt="Cerberus logo" width="48" align="right">

# Cerberus

A desktop workspace for chat, documents, and research with local or cloud AI.

[![Checks](https://github.com/23lambi/Cerberus-ai/actions/workflows/checks.yml/badge.svg)](https://github.com/23lambi/Cerberus-ai/actions/workflows/checks.yml)
[![MIT license](https://img.shields.io/badge/license-MIT-737373)](LICENSE)

[Get started](#get-started) · [AI engines](#ai-engines) · [User guide](docs/guide.md)

## Get started

Download the launcher for your computer. **No Python, Git, or terminal setup is required.**

| Your computer | Download | Open after extracting the ZIP |
| --- | --- | --- |
| Windows · 64-bit | [Windows launcher](https://github.com/23lambi/Cerberus-ai/releases/latest/download/cerberus-launcher-windows-x86_64.zip) | `CerberusLauncher.exe` |
| macOS · Apple Silicon | [Mac launcher · Apple Silicon](https://github.com/23lambi/Cerberus-ai/releases/latest/download/cerberus-launcher-macos-arm64.zip) | `CerberusLauncher.app` |
| macOS · Intel | [Mac launcher · Intel](https://github.com/23lambi/Cerberus-ai/releases/latest/download/cerberus-launcher-macos-x86_64.zip) | `CerberusLauncher.app` |
| Linux · 64-bit | [Linux launcher](https://github.com/23lambi/Cerberus-ai/releases/latest/download/cerberus-launcher-linux-x86_64.zip) | `CerberusLauncher` |

1. Download and extract your launcher ZIP.
2. Open the launcher and choose **Install Cerberus**, then **Open Cerberus**.
3. Choose your AI engine and model in **Settings → Setup check**.

The launcher detects your platform and handles app downloads, updates, and repairs.
Your chats and settings are kept separately from the application.

Downloads require a published stable release. Check [Releases](https://github.com/23lambi/Cerberus-ai/releases)
for availability. Linux is tested locally; Windows and macOS still need native
release testing. Initial packages are unsigned.
[Platform requirements and help →](docs/launcher.md)

## Built for everyday work

- **Chat your way** — regular conversations, Deep think, images, and tools.
- **Keep work together** — projects, file attachments, and searchable documents.
- **Write and revise** — Markdown editing, version history, and AI edits you review.
- **Remember what matters** — saved facts available across your chats.
- **Research with sources** — web search and reports with numbered citations.
- **Own your data** — local storage, full backups, and Markdown or JSON exports.

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

[User guide](docs/guide.md) · [Contributing](CONTRIBUTING.md) · [Project layout](docs/development/architecture.md) · [Build releases](docs/launcher.md#build-and-publish)

## Feedback & license

Found a bug or have an idea? [Open an issue](https://github.com/23lambi/Cerberus-ai/issues/new/choose).

[MIT licensed](LICENSE). Bundled libraries retain their [own licenses](static/vendor/README.md).
