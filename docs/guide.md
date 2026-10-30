# Cerberus guide

[← Back to the README](../README.md)

A local AI chat workspace built with FastAPI, SQLite, plain JavaScript and
your choice of AI engine. Run from this project directory:

```bash
source venv/bin/activate
uvicorn main:app --reload
```

Open http://127.0.0.1:8000 and choose an AI engine in Setup.

## Choosing an AI engine

Open **Settings → Setup check → 1. Choose your AI**. Start with
**On this computer** for Ollama, llama.cpp, LM Studio or Jan, or **Cloud
service** for Hugging Face, OpenAI, Groq or OpenRouter. Ollama is the easiest
local setup. Cloud providers ask for an API key; their usual address is
already filled in under **Connection settings**. **Custom connection**
lets you connect to another OpenAI-compatible server. Connect, then choose
a model in chat.

Start local servers separately: enable LM Studio's or Jan's API server,
or run `llama-server -m your-model.gguf --jinja` for llama.cpp and use
`http://127.0.0.1:8080/v1` under **Connect to an existing server instead**.
Alternatively, choose llama.cpp, enter the full path to a GGUF model, and
choose **Start with Cerberus**. **Advanced** contains the `llama-server`
executable path and local port if you need to change their defaults. After a successful
start, Cerberus selects that server and starts it automatically on future
launches while llama.cpp remains selected. It uses an 8192-token context and
enables Jinja chat templates for tools. Loading may take up to two minutes;
startup failures point to `llamacpp.log` in the system app-data folder.
**Stop & disable automatic start** stops Cerberus's server and turns off
automatic startup. Closing Cerberus also stops its server. Servers started
separately are left running. Stop the managed server before changing its
model or port; switching engines alone leaves it running until you stop it
or close Cerberus. GGUF files and llama.cpp are installed separately.
Chat, Deep think and Research use the chosen engine; image and tool support
depend on the model and server. The Models browser manages Ollama models.

Cloud engines show a ☁ badge and send messages and supplied context to the
configured provider. API keys are stored separately from the database in
the system app-data folder's `keys.json`, excluded from backups and never
returned to the browser. Re-enter keys after restoring on another computer.
Search by meaning still uses local Ollama embeddings; without them,
document retrieval falls back to keywords.

## Setup window

When something important is missing (no running AI engine, or no chat
model), a **Set up Cerberus** window opens by itself; open it any time from
Settings → Setup check. It keeps the essentials first:

1. **Choose your AI.** Choose an engine as described above. With Ollama selected,
   an installed and running Ollama is simply used. If
   it's installed but not running, the window shows how to start it (Cerberus
   doesn't start a system Ollama itself: run as you instead of as its service,
   it would look for models elsewhere). If Ollama is missing, **Download & run
   Ollama** fetches the official ready-to-run version (about 1.5 GB, 220 MB on
   macOS) into the system's app folder, with resume after an interruption, and
   Cerberus starts and stops that copy together with itself. No admin rights.
2. **Your chat model.** Suggests a first chat model that fits your memory,
   downloadable with one click. **Better document search** is optional and
   starts collapsed.

**Optional · Web search** also starts collapsed. Choose a search engine and
press **Save & test** for a real test search. With SearXNG chosen and not yet
running, choose **Install it for me** (Cerberus installs and runs its own
SearXNG, no Docker) or **Use Docker instead** (shows the commands to copy).
Once your AI and a chat model are ready, choose **Start chatting**; optional
features can wait.

## Desktop app

Cerberus can also run in its own window, with an icon in your app menu, on
Linux, macOS and Windows. You need Python 3.14 and an AI engine. Once, from the
Cerberus folder:

```bash
# Linux and macOS
python3 -m venv venv
venv/bin/pip install -r requirements.txt
sh install-desktop.sh          # Linux: app menu; macOS: ~/Applications/Cerberus.app
```

```powershell
# Windows (PowerShell)
py -m venv venv
venv\Scripts\pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File install-desktop.ps1   # Start menu
```

The window uses the system's own browser engine on Windows (WebView2) and
macOS (WebKit). Linux has none built in, so pip installs Qt WebEngine (about
540 MB). Then start **Cerberus** from the app menu, or run `desktop.py` with
the venv's Python.

Your data stays in the project folder if `cerberus.db` is already there.
New installs keep it in the system's app-data folder: `~/.local/share/cerberus`
(Linux), `~/Library/Application Support/Cerberus` (macOS) or
`%LOCALAPPDATA%\Cerberus` (Windows). Set `CERBERUS_DATA` to choose another
folder. Settings → Your data shows where it is. Only Linux is tested by the
author; macOS and Windows are prepared but untested.
The app starts the server in the background and stops it when you close the
window. If Cerberus is already running (for example with uvicorn), the window
uses that server and leaves it running. Backups and chat exports are saved to
`~/Downloads`; links to websites open in your normal browser. Set
`CERBERUS_PORT` to use another port than 8000. Remove the menu entry with
`rm ~/.local/share/applications/cerberus.desktop`. The embedding
model is `nomic-embed-text`; without it, retrieval falls back to keywords.
Use one server worker: active answers and Stop are managed within that process.

## Foundation behavior

- Chat requests validate message roles/order, text, image counts and sizes.
  Stale browser history returns a clear error instead of appending duplicate turns.
- Stop cancels preparation or generation and waits for saving to finish. If an
  answer has started, its partial text and question are saved together. Stopping
  during Deep think's draft/review saves nothing; stopping during the final
  answer saves the partial final answer. A disconnect also keeps partial answers.
- Each question/answer pair is one database transaction. A chat cannot be deleted
  or regenerated while answering. Regenerate clears its obsolete summary/recap.
- Personal memories are global. Documents and past-chat retrieval are scoped to
  the current project; normal chats search only normal chats/documents. Existing
  documents remain in All chats. Upload while inside a project to scope a file.
  Deleting a project also deletes its documents and original files.
- Prompt budgeting estimates text, images, tools and output space. It drops older
  complete turns, summarizes older history, caps auxiliary context, and rejects
  an oversized current turn with an actionable message. Estimates vary by model;
  the token statistics returned by Ollama remain the actual counts.

## Chat attachments

To delete several conversations, choose **Select chats** above the chat list,
tick individual chats or **Select all shown**, then **Delete selected** and
confirm. Selection applies to the current project and search results. Failed
deletions remain selected with an error message; answering chats must be stopped
before deletion. **Cancel selection** returns to normal chat navigation.

Use **+** beside the chat input to attach a file to that chat only. Its text is
included directly when answering, including questions like “what does this say?”.
After sending, file chips move from the input area into the conversation.
Attachments appear in the conversation when reopening it and are removed when deleting it.
They do not enter the shared All chats or project document search. Large files
may exceed the context budget; remove or shorten them if prompted. Files uploaded
through **Documents** remain shared within their existing scope.

Click a file chip before or after sending to open a read-only text preview.
PDF previews show extracted text rather than the original page layout.

Answers supplied with documents show numbered source buttons. When the model
writes a reference such as `[1]`, it becomes clickable if that source exists.
The model may omit inline references; the source list remains available. The
list shows evidence supplied to the model, not an automatic guarantee that
every claim is supported. Click a source to inspect the exact text supplied
for that answer, then **View current document** to compare it with today's file.
Source snapshots are saved with the answer and included in backups and JSON
exports, so edits or deletion of the original do not erase earlier evidence.
Existing answers generated before this feature do not gain source snapshots.

## Workspace documents

**Docs** and **Memory** in the sidebar open separate screens. Memory holds
facts used across chats; Docs holds your workspace files and editable notes.

Open **Docs** in the sidebar (inside a project for that project's files).
Choose **Upload**, drop files anywhere on the page, or choose **New note**.
The line above the buttons says whose documents these are ("All chats" or the
project) and how many; **Filter documents** narrows the list by title, file
name or kind (Escape clears it).
Each document shows its title (a note's first `#` heading), whether it's an
uploaded file, a note or a research report, its size and when it changed.
Click a document to open it: a note opens in the editor, an uploaded file
shows the text Cerberus read from it. Editable notes support a filename,
Markdown editor, sanitized preview, and saved version history. In the **⋯**
menu, **Edit a copy** turns an uploaded file into an editable Markdown copy
(its original is preserved), and **Remove** deletes it.

**How documents reach the chat.** Cerberus cuts each document into pieces and
searches them for every message; the best-fitting pieces are given to the
model and shown as numbered sources. That suits questions about details.
For a whole document ("summarise it"), choose **Ask**: it starts a new chat
with a copy attached, and the model then reads all of it.
In a project chat, **Save as document** beneath an answer opens that answer in
the editor. Choose a filename and save it to the current project.

Save a document before requesting an AI edit. Describe the change and choose
**Propose edit**; it uses the model selected in chat. Review the diff, then
choose **Apply proposed changes** or **Discard proposal**. Generating a proposal
does not change the saved document. Saves and proposals reject stale revisions
so another tab cannot overwrite newer work. AI edits have a three-minute limit;
documents too large for the context budget and truncated outputs are rejected.

Each save records a version and replaces its retrieval chunks in the same
transaction. Missing embeddings fall back to keyword search. History can load
an older version into the editor; saving creates a new version. Editable content,
history, and proposals live in SQLite and are included in full backups. Project
deletion removes them. All chats can also have their own Markdown documents.

## Web search

Open **Options** beside the model list and turn on **Web** to let Cerberus search the web. It works
with every model and in Deep think. With Web off, Cerberus does not search
the web; cloud engines still receive messages and supplied context.
Cerberus searches only when a message needs it: not for "hello", thanks,
arithmetic, writing tasks or questions about your memories ("Web: not
needed"). With the Helper model on, the Helper decides and rewrites follow-ups
such as "and when was it released?" into a real query; without it, rules
decide and add your previous question to short follow-ups. The query used is
shown above the sources. A web answer takes longer on a CPU, mostly because the
model reads the pages. Cerberus asks the search engine you chose, reads the top three pages, and gives the model only the
pieces that best fit your question. They appear as 🌐 source buttons; click
one to see the exact text used and to open the page. The answer label says
"Web: 3 pages" whenever the web was asked.

Choose the engine under Settings → Web search (or in Setup):

| Engine | Needs | Good to know |
| --- | --- | --- |
| [SearXNG](https://docs.searxng.org/) | Installing once | Private, free, asks many engines at once. |
| DuckDuckGo | Nothing | May ask for a CAPTCHA after many searches in a row. |
| [Brave Search](https://api-dashboard.search.brave.com/) | A free API key | An official API, reliable. |
| [Tavily](https://app.tavily.com/) | A free API key | A search API made for AI assistants. |

API keys are kept with your other keys, never in the database or backups.
Your search words go to the engine you choose.

**SearXNG without Docker.** In Setup → Web search, **Install it for me**
downloads SearXNG with Git into Cerberus's app folder, gives it its own
Python environment (about 180 MB), and runs it on `127.0.0.1:8888`, only for
this computer. It starts and stops with Cerberus; **Remove it** deletes it.
It needs Git and works on Linux and macOS. SearXNG doesn't officially support
Windows: the install may work, but Docker or DuckDuckGo are surer there.

**SearXNG with Docker.** Settings go in `~/searxng/settings.yml` with `json`
enabled under `search: formats:` (**Use Docker instead** writes it). On Linux:

```bash
sudo systemctl enable --now docker
sudo docker run -d --name searxng --restart unless-stopped \
  -p 127.0.0.1:8888:8080 -v ~/searxng:/etc/searxng docker.io/searxng/searxng:latest
```

With Docker Desktop on Windows or macOS, run the same `docker run` without
`sudo`.

**Run SearXNG switch.** Shown under Settings → Web while SearXNG is chosen.
On, SearXNG runs while Cerberus is open and stops when you close Cerberus;
off, it stays stopped. It switches Cerberus's own SearXNG, and a Docker one
named `searxng` where Docker works without `sudo` (Docker Desktop, or Linux
in the `docker` group). Otherwise it shows the `docker` command to run. If the engine fails, you still get an answer with a note saying why.

Pages are read as text only; nothing on them runs. Cerberus never opens
addresses on your computer or home network, checks this again after every
redirect, and limits each page to 10 seconds and 2 MB. Web pages can be wrong
or contain hidden instructions: the model is told to treat them as information
only, but check important facts with the source.

## Models

Open **Models** in the sidebar. **Your models** shows your Ollama collection
with download sizes and abilities in plain language. **Use in chat** selects
a chat model and takes you back to the conversation. **Model details** holds
technical information; document-search models have no chat button.

**Find models → Local apps** finds models exposed by running LM Studio,
Jan and llama.cpp servers at their usual local addresses, plus your configured
local engine address. Start the app's API server, press **Refresh**, then
choose **Use in chat** to connect Cerberus to that app and select the model.
It lists models the server exposes, rather than searching your disk for files.

The Ollama and Hugging Face sources open the download libraries when you need them. Downloads
stay visible while switching views. **Filter and sort** and **Download by
model name** start collapsed. In the Ollama library, browse all models,
**Popular** or **Newest** first, with filters (Chat, Vision, Tools, Thinking,
Embedding). Click a size to download it; sizes you already have show a check
mark. You can also **Search** (only your search words are sent to ollama.com)
or type an exact name such as `qwen3:4b`. The list is kept for an hour. A download shows its progress and can
be cancelled; downloading again continues where it stopped. **Delete** frees
the disk space. New models appear in the chat's model list right away.

Switch the source to **Hugging Face** to browse GGUF models (Hugging Face's
official API): **Popular**, **Trending** or **Most liked**, in the categories
**Chat**, **Vision** and **Embedding**, 30 at a time, or search over a million
models. There is no "newest" or "all": brand-new uploads are often spam, and
other categories (image, music, speech) can't run in Ollama. Models you have
in any version are marked installed. **Choose version** lists the common versions
with their sizes; ★ marks Q4_K_M, the usual choice, and **Show all** lists the
rest. Downloads go through Ollama (as `hf.co/<publisher>/<model>:<version>`),
so these models appear in the chat's list like any other. Gated models, which
need a Hugging Face account, are marked and can't be downloaded here. Prefer
well-known publishers and many downloads: anyone can upload a model.

The search reads ollama.com's normal search page, because Ollama has no
search API. If that page changes, search may find nothing; typing an exact
name always works, because downloads use Ollama's official API.

## Research agent

Open **Options** beside the model list and turn on **Research** and ask a bigger question, such as
"Compare Ollama and llama.cpp for running local LLMs". Cerberus plans up to
four web searches, reads the two best new pages for each, keeps the most
relevant parts, and writes a structured report with numbered citations. You
see each step while it works, and Stop works at every step. The finished
report is saved as a Markdown document (with a Sources list of links) in the
chat's project, or in All chats; **Open report** opens it in the editor.

It needs web search (see Web search). The model you selected plans and writes,
so a larger model plans better searches and cites more reliably. On a CPU a
report takes one to a few minutes. The model gets no tools that change
anything: the code runs the steps, the model only writes the plan and report.

## Backup and export

Open Settings → Backup and export. Download a full ZIP backup or export the
current chat as Markdown or JSON. JSON retains images and image descriptions.

A backup contains a consistent SQLite snapshot, original document files,
`documents.json` mapping their paths, and `RESTORE.txt`. Stop Cerberus before
restoring; keep a copy of your existing data, replace `cerberus.db` (deleting
any old `cerberus.db-wal` and `cerberus.db-shm` beside it), and copy
documents to the paths in the manifest. Models and application code are separate.
The download stays on your computer and includes your private data.

## Checks

```bash
venv/bin/python -m pytest -q
node tests/frontend.test.cjs
```

Python tests use temporary databases and fake models; they do not modify your
conversations or require a running Ollama instance.
