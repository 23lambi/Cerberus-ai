# Cerberus

A local AI chat workspace built with FastAPI, SQLite, plain JavaScript and
Ollama. Run from this project directory:

```bash
source venv/bin/activate
uvicorn main:app --reload
```

Open http://127.0.0.1:8000. Ollama must be running separately.

## Desktop app

Cerberus can also run in its own window, with an icon in your app menu, on
Linux, macOS and Windows. You need Python 3.14 and Ollama. Once, from the
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

Enter a project and open **Documents** in the sidebar. Upload files or choose
**New Markdown document**. Editable documents support a filename, Markdown
editor, sanitized preview, and saved version history. **Read / copy** opens an
uploaded file as a new editable Markdown copy; its original is preserved.
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

Turn on **Web** beside the message box to let Cerberus search the web. It works
with every model and in Deep think. Without it, nothing leaves your computer.
Cerberus searches only when a message needs it: not for "hello", thanks,
arithmetic, writing tasks or questions about your memories ("Web: not
needed"). With the Helper model on, the Helper decides and rewrites follow-ups
such as "and when was it released?" into a real query; without it, rules
decide and add your previous question to short follow-ups. The query used is
shown above the sources. A web answer takes longer on a CPU, mostly because the
model reads the pages. Cerberus asks [SearXNG](https://docs.searxng.org/), a search engine
running locally, reads the top three pages, and gives the model only the
pieces that best fit your question. They appear as 🌐 source buttons; click
one to see the exact text used and to open the page. The answer label says
"Web: 3 pages" whenever the web was asked.

One-time setup (Docker, settings in `~/searxng/settings.yml` with `json`
enabled under `search: formats:`):

```bash
sudo systemctl enable --now docker
sudo docker run -d --name searxng --restart unless-stopped \
  -p 127.0.0.1:8888:8080 -v ~/searxng:/etc/searxng docker.io/searxng/searxng:latest
```

Change the address under Settings → Web search. If SearXNG is down, you still
get an answer with a note saying why; start it with `sudo docker start searxng`.

Pages are read as text only; nothing on them runs. Cerberus never opens
addresses on your computer or home network, checks this again after every
redirect, and limits each page to 10 seconds and 2 MB. Web pages can be wrong
or contain hidden instructions: the model is told to treat them as information
only, but check important facts with the source.

## Models

Open **Models** in the sidebar to manage Ollama's models. It lists the
installed models with their size and abilities (vision, tools, thinking), and
which ones are in memory now. Below them is the Ollama library: all models,
**Popular** or **Newest** first, with filters (Chat, Vision, Tools, Thinking,
Embedding). Click a size to download it; sizes you already have show a check
mark. You can also **Search** (only your search words are sent to ollama.com)
or type an exact name such as `qwen3:4b`. The list is kept for an hour. A download shows its progress and can
be cancelled; downloading again continues where it stopped. **Delete** frees
the disk space. New models appear in the chat's model list right away.

The search reads ollama.com's normal search page, because Ollama has no
search API. If that page changes, search may find nothing; typing an exact
name always works, because downloads use Ollama's official API.

## Research agent

Turn on **Research** beside the message box and ask a bigger question, such as
"Compare Ollama and llama.cpp for running local LLMs". Cerberus plans up to
four web searches, reads the two best new pages for each, keeps the most
relevant parts, and writes a structured report with numbered citations. You
see each step while it works, and Stop works at every step. The finished
report is saved as a Markdown document (with a Sources list of links) in the
chat's project, or in All chats; **Open report** opens it in the editor.

It needs SearXNG (see Web search). The model you selected plans and writes,
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
