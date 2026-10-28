<img src="static/cerberus.svg" alt="Cerberus logo" width="48" align="right">

# Cerberus

**A desktop workspace for chat, documents, and research.** Use local AI for
private work or connect a cloud model when you need one.

[![Checks](https://github.com/23lambi/Cerberus-ai/actions/workflows/checks.yml/badge.svg)](https://github.com/23lambi/Cerberus-ai/actions/workflows/checks.yml)
[![Apache 2.0](https://img.shields.io/badge/license-Apache_2.0-737373)](LICENSE)

[Download](#download) · [What it does](#what-it-does) · [AI engines](#ai-engines) · [Guide](docs/guide.md) · [Issues](https://github.com/23lambi/Cerberus-ai/issues/new/choose)

## Download

**The release build has passed.** Download links will be ready after the draft
release is reviewed and published.

[Windows](https://github.com/23lambi/Cerberus-ai/releases) · [macOS](https://github.com/23lambi/Cerberus-ai/releases) · [Linux](https://github.com/23lambi/Cerberus-ai/releases) · [Build status](https://github.com/23lambi/Cerberus-ai/actions/workflows/release.yml)

When the release is published, choose the launcher ZIP for your computer, extract
it, and open the launcher. It installs and updates Cerberus; your chats and
settings stay in your user data folder. No Python or Git setup is needed.

<details>
<summary>Choose the right launcher</summary>

| Computer | Download | Open |
| --- | --- | --- |
| Windows, 64-bit | `cerberus-launcher-windows-x86_64.zip` | `CerberusLauncher.exe` |
| macOS, Apple Silicon | `cerberus-launcher-macos-arm64.zip` | `CerberusLauncher.app` |
| macOS, Intel | `cerberus-launcher-macos-x86_64.zip` | `CerberusLauncher.app` |
| Linux, 64-bit | `cerberus-launcher-linux-x86_64.zip` | `CerberusLauncher` |

Initial builds are unsigned. See [supported platforms and requirements](docs/launcher.md#supported-builds).

</details>

<p align="center">
  <img src="docs/assets/chat.png" alt="Cerberus desktop chat with connection status, prompt suggestions, and a compact message composer" width="100%">
</p>
<p align="center"><sub>Chat interface shown with sample data.</sub></p>

## What it does

- **Chat:** streaming responses, Deep think, image input, and tools.
- **Documents:** organize projects, search files, edit Markdown, and review AI changes before applying them.
- **Memory:** save useful facts across conversations.
- **Research:** search the web and get reports with citations.
- **Your data:** keep chats and documents locally; create backups and Markdown or JSON exports.

## AI engines

| Run locally | Connect to cloud |
| --- | --- |
| Ollama · llama.cpp · LM Studio · Jan | Hugging Face · OpenAI · Groq · OpenRouter |

Other OpenAI-compatible servers work too. Image and tool support depends on the
engine and model. Cerberus can start its managed llama.cpp server or install its
own Ollama. Optional web search and Research use SearXNG.

In the app, open **Models** to manage Ollama models, find downloads, or connect
to a running local app. Choose **Use in chat** to select a model.
[Engine setup guide](docs/guide.md#choosing-an-ai-engine)

## Privacy

Local chats and documents stay on your computer. When you use a cloud engine,
your messages and the context you provide go to that service. Web search also
contacts the configured search service and the pages it opens. API keys are
stored separately from the chat database and are excluded from backups.

## Build from source

The desktop app uses FastAPI, SQLite, JavaScript, and pywebview. Packaged releases
do not require Python or Git. Source setup and test commands are in the section below.

<details>
<summary>Source setup · Python 3.14</summary>

```bash
git clone https://github.com/23lambi/Cerberus-ai.git
cd Cerberus-ai
```

**Linux and macOS**

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
sh install-desktop.sh
```

**Windows PowerShell**

```powershell
py -3.14 -m venv venv
venv\Scripts\pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File install-desktop.ps1
```

Run checks:

```bash
venv/bin/python -m pytest -q
node tests/frontend.test.cjs
```

</details>

[User guide](docs/guide.md) · [Contributing](CONTRIBUTING.md) · [Project layout](docs/development/architecture.md) · [Release process](docs/releasing.md)

## Feedback and license

[Report a bug or suggest an improvement](https://github.com/23lambi/Cerberus-ai/issues/new/choose). Cerberus project code is licensed under [Apache 2.0](LICENSE); bundled libraries retain their [own licenses](static/vendor/README.md).
