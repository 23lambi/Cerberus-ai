<p align="center">
  <img src="static/mascot.svg" alt="Cerberus mascot: a crimson pixel-art dog with three heads" width="200">
</p>

<h1 align="center">Cerberus</h1>

<p align="center">
  <b>A desktop workspace for chat, documents, and research.</b><br>
  Local AI for private work. A cloud model when you need one.
</p>

<p align="center">
  <a href="https://github.com/23lambi/Cerberus-ai/releases/latest"><img src="https://img.shields.io/github/v/release/23lambi/Cerberus-ai?label=release&color=dc143c" alt="Latest release"></a>
  <a href="https://github.com/23lambi/Cerberus-ai/actions/workflows/checks.yml"><img src="https://github.com/23lambi/Cerberus-ai/actions/workflows/checks.yml/badge.svg" alt="Checks"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-737373" alt="Apache 2.0"></a>
</p>

<p align="center">
  <a href="#download">Download</a> ·
  <a href="#what-it-does">What it does</a> ·
  <a href="#ai-engines">AI engines</a> ·
  <a href="docs/guide.md">Guide</a> ·
  <a href="https://github.com/23lambi/Cerberus-ai/issues/new/choose">Issues</a>
</p>

<p align="center">
  <img src="docs/assets/chat.png" alt="Cerberus desktop chat with prompt suggestions and a compact message composer" width="100%">
  <br><sub>Chat interface shown with sample data.</sub>
</p>

## Download

<p align="center">
  <a href="https://github.com/23lambi/Cerberus-ai/releases/latest/download/cerberus-launcher-windows-x86_64.zip"><img src="https://img.shields.io/badge/Windows-64--bit-dc143c?style=for-the-badge" alt="Download for Windows"></a>
  <a href="https://github.com/23lambi/Cerberus-ai/releases/latest/download/cerberus-launcher-macos-arm64.zip"><img src="https://img.shields.io/badge/macOS-Apple_Silicon-dc143c?style=for-the-badge" alt="Download for macOS, Apple Silicon"></a>
  <a href="https://github.com/23lambi/Cerberus-ai/releases/latest/download/cerberus-launcher-macos-x86_64.zip"><img src="https://img.shields.io/badge/macOS-Intel-dc143c?style=for-the-badge" alt="Download for macOS, Intel"></a>
  <a href="https://github.com/23lambi/Cerberus-ai/releases/latest/download/cerberus-launcher-linux-x86_64.zip"><img src="https://img.shields.io/badge/Linux-64--bit-dc143c?style=for-the-badge" alt="Download for Linux"></a>
</p>

1. **Download** the launcher for your computer and extract the ZIP.
2. **Open the launcher**, choose where to install, and click **Install Cerberus**.
3. **Start chatting.** The launcher opens Cerberus when it's done.

Cerberus updates itself from **Settings → Updates**. Your chats and settings stay
in your user data folder. No Python or Git setup is needed.
[All releases](https://github.com/23lambi/Cerberus-ai/releases)

<details>
<summary><b>Which file do I need?</b></summary>

| Computer | Download | Open |
| --- | --- | --- |
| Windows, 64-bit | `cerberus-launcher-windows-x86_64.zip` | `CerberusLauncher.exe` |
| macOS, Apple Silicon | `cerberus-launcher-macos-arm64.zip` | `CerberusLauncher.app` |
| macOS, Intel | `cerberus-launcher-macos-x86_64.zip` | `CerberusLauncher.app` |
| Linux, 64-bit | `cerberus-launcher-linux-x86_64.zip` | `CerberusLauncher` |

See [supported platforms and requirements](docs/launcher.md#supported-builds).

</details>

<details>
<summary><b>"Windows protected your PC" or "macOS cannot verify"?</b></summary>

The launcher is not yet signed by a verified developer, so your system asks
once before opening it:

- **Windows:** choose **More info → Run anyway**.
- **macOS:** open `CerberusLauncher.app`; when macOS says it cannot verify it,
  choose **Done**, then open **System Settings → Privacy & Security** and choose
  **Open Anyway** next to CerberusLauncher.
- **Linux:** if double-clicking does nothing, run `chmod +x CerberusLauncher`
  in the extracted folder, then open it again.

</details>

## What it does

<table>
  <tr>
    <td width="50%" valign="top">
      <h3>💬 Chat</h3>
      Streaming answers, image input, and tools. <b>Deep think</b> drafts,
      reviews, then answers: three heads, one answer.
    </td>
    <td width="50%" valign="top">
      <h3>📄 Documents</h3>
      Organize projects, search files, edit Markdown, and review AI changes
      before applying them.
    </td>
  </tr>
  <tr>
    <td valign="top">
      <h3>🔎 Research</h3>
      Search the web and get reports with citations, saved as documents.
    </td>
    <td valign="top">
      <h3>🧠 Memory</h3>
      Save useful facts once, and Cerberus remembers them in every conversation.
    </td>
  </tr>
  <tr>
    <td colspan="2" valign="top">
      <h3>🔒 Your data stays yours</h3>
      Chats and documents live on your computer. Create backups and export chats
      as Markdown or JSON at any time.
    </td>
  </tr>
</table>

## AI engines

| 🖥️ Run locally | ☁️ Connect to cloud |
| --- | --- |
| Ollama · llama.cpp · LM Studio · Jan | Hugging Face · OpenAI · Groq · OpenRouter |

Other OpenAI-compatible servers work too. Image and tool support depends on the
engine and model. Cerberus can start its managed llama.cpp server or install its
own Ollama. Optional web search and Research use SearXNG.

In the app, open **Models** to manage Ollama models, find downloads, or connect
to a running local app. Choose **Use in chat** to select a model.
[Engine setup guide →](docs/guide.md#choosing-an-ai-engine)

## Privacy

> [!NOTE]
> Local chats and documents stay on your computer. When you use a cloud engine,
> your messages and the context you provide go to that service. Web search also
> contacts the configured search service and the pages it opens. API keys are
> stored separately from the chat database and are excluded from backups.

## Build from source

The desktop app uses FastAPI, SQLite, JavaScript, and pywebview. Packaged releases
do not require Python or Git.

<details>
<summary><b>Source setup · Python 3.14</b></summary>

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

The pixel mascot is drawn by `scripts/make_mascot.py`; edit its pixel rows and
run it again to change the mascot and its animations.

</details>

[User guide](docs/guide.md) · [Contributing](CONTRIBUTING.md) · [Project layout](docs/development/architecture.md) · [Release process](docs/releasing.md)

## Feedback and license

Found a bug or have an idea? [Open an issue](https://github.com/23lambi/Cerberus-ai/issues/new/choose).

Cerberus project code is licensed under [Apache 2.0](LICENSE); bundled libraries
retain their [own licenses](static/vendor/README.md).
