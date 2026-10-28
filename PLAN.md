# Cerberus — roadmap and session handoff

Last updated: 2026-10-28.

**2026-10-28:** Stages 1 and 2 (with all follow-ups below) are committed.
139 Python tests and 13 frontend checks passed before the commit. Next:
small improvements (database indexes, fewer full chat loads, WAL mode,
memory.js error handling), then the real-model smoke checks, then Stage 3.

## Goal

Grow Cerberus into a private, local AI workspace, inspired by the capabilities
of [Odysseus](https://github.com/odysseus-dev/odysseus). Keep Cerberus's own
identity, Ollama integration, and understandable code. The existing FastAPI,
SQLite, and plain JavaScript stack can support the next stages.

The user authorized stages 1 and 2. Stage 2 is now implemented locally.
Stages 3 onward remain proposed work.

## Current application

- Streaming local chat, model selection, Think, Stop, and Regenerate.
- SQLite persistence for chats, projects, memories, documents, and settings.
- Guard routes questions toward chat or memory retrieval.
- Keeper searches memories, document chunks, and earlier chats.
- Project recaps carry context between chats in the same project.
- Optional Helper handles background jobs; Eyes describes images.
- Deep think produces a draft, reviews it, and writes a final answer.
- Tool calling supports calculation, time, memory search, and saving memories.
- Reverse inspects files without executing them, extracts strings/imports,
  disassembles Linux x86-64 programs, and supports questions about the findings.

## Stage 1 — foundation

Status: implemented; automated checks pass. Real-model normal chat, retrieval
and backups were smoke-tested during Stage 2. Real-model Stop/Regenerate/Deep
think checks remain pending. Changes are saved locally and are **not committed**.

- [x] Validate chat roles/order, nonempty messages, model names, image counts,
  base64 data, and payload sizes.
- [x] Reject missing chats/projects and stale browser history.
- [x] Save each question/answer pair in one SQLite transaction.
- [x] Share the generation lifecycle between chat and Deep think.
- [x] Stop preparation or generation and confirm saving before ending the stream.
- [x] Preserve partial answers on Stop, model failure, and disconnect.
- [x] Prevent deletion/regeneration while a chat is answering.
- [x] Clear obsolete summaries and recaps when regenerating.
- [x] Scope documents and past-chat retrieval to the current project.
- [x] Budget prompt space for text, images, tools, and answer tokens.
- [x] Add full ZIP backup downloads and Markdown/JSON chat exports in Settings.
- [x] Document startup, behavior, backups, and restoration in README.md.
- [x] Add regression coverage for backend lifecycle and browser state handling.

### Decisions to preserve

- Personal memories remain global. Project documents and past-chat search stay
  inside their project; normal chats retrieve normal-chat documents/history.
- Existing documents migrate into All chats. Upload from within a project to
  associate a new document with that project.
- Deleting a project removes its documents and their original files too.
- Stopping Deep think during draft/review saves no turn. Once the final answer
  starts, stopping saves that partial final answer.
- Context budgeting uses estimates, not a model-specific tokenizer. Ollama's
  returned statistics remain the actual token counts.
- Use **one server worker**: active runs and Stop are tracked in that process.
- A backup contains a consistent database snapshot, original documents, a path
  manifest, and restore instructions. Models and application code are separate.

### Main files changed or added

- `cerberus/schemas.py`: request validation.
- `cerberus/turns.py`: shared generation, cancellation, and save lifecycle.
- `cerberus/database.py`: atomic turn saves, document migration/scope, snapshot.
- `cerberus/budget.py`: prompt size estimates and complete-turn trimming.
- `cerberus/context.py`, `keeper.py`, `ollama.py`, `tools.py`: retrieval,
  budgeting, and stream cleanup.
- `cerberus/routes/`: chat, council, project, document, backup, and export routes.
- `static/`: Stop/reconciliation, project document UI, and Settings downloads.
- `tests/test_foundation.py`, `tests/frontend.test.cjs`: new regression coverage.

### Verification already completed

- Full Python suite: **113 passed** before the last two regression tests were
  added. The final foundation-only run passed **28 tests**, including those two
  new tests for in-flight cancellation and ASGI disconnect cleanup.
- Frontend checks: **4 passed** with `node tests/frontend.test.cjs`.
- JavaScript syntax checks and `git diff --check` passed.
- Python tests used temporary databases and fake models. No real Ollama model
  was exercised, and no visual browser inspection was performed.
- FastAPI's test client hung inside the execution sandbox; the Python suite
  passed when run outside it. No dependency changes were needed.

## Resume here next session

1. Read this file and README.md, then inspect `git status` and the diff. Preserve
   the existing uncommitted stage 1 and stage 2 work.
2. Run the full suite once to include the final two tests in a single result:

   ```bash
   venv/bin/python -m pytest -q
   node tests/frontend.test.cjs
   ```

3. Start Ollama and Cerberus from the project directory:

   ```bash
   source venv/bin/activate
   uvicorn main:app --reload
   ```

4. Smoke-test in the browser at http://127.0.0.1:8000:
   - Send, Stop mid-answer, reopen, and Regenerate a normal chat.
   - Stop Deep think both before and during its final answer.
   - Upload different documents into two disposable projects; confirm each
     project retrieves its own files and earlier chats.
   - Confirm normal chats can still use existing All chats documents.
   - Download a full backup and export a chat from Settings.
   - Check that an oversized prompt produces a useful error.
5. Fix any smoke-test findings, review the diff, and commit when requested.
6. Review the Stage 2 implementation below with the user. Discuss stage 3 scope
   before beginning it.

## Stage 2 and later roadmap

### Stage 2 — workspace documents

Status: implemented locally, not committed.

- [x] Documents sidebar shortcut, scoped list, Markdown editor and sanitized preview.
- [x] Save project chat answers as documents.
- [x] Read uploaded files and save editable Markdown copies without changing originals.
- [x] AI edit instructions, reviewable unified diff, explicit Apply and Discard.
- [x] Revision checks reject stale saves and stale/repeated proposal application.
- [x] Every save records a version and atomically replaces Keeper retrieval chunks.
- [x] Load earlier versions into the editor; Save restores as a new version.
- [x] Workspace content, history and proposals are included in SQLite backups and
  removed when deleting their document/project.
- [x] Regression coverage for scope, saves, history, proposals, failures and backups.

Implementation notes:
- Uploaded originals retain their existing paths and remain unchanged. Editable
  Markdown documents live in SQLite (`content`, `revision`, `document_versions`,
  `document_proposals`); their empty `path` distinguishes them in backups/deletion.
- Semantic embeddings are prepared before saving. Content, chunks and history
  commit together under a revision check. Missing embeddings use keyword search.
- AI proposals use the selected chat model, with a 1,800-token output budget and
  a three-minute limit. Oversized input, empty output and truncated output fail
  without changing the document. Proposals are never indexed until applied.
- Main changes: `database.py`, `routes/documents.py`, `keeper.py`, `routes/backup.py`,
  `static/documents.js`, `app.js`, `index.html`, `style.css`, `tests/test_workspace.py`.

Chat attachment follow-up on 2026-10-18:
- Chat **+** uses a separate picker, creates the chat first, and uploads with
  `chat_id`. Attachments are excluded from shared lists and retrieval indexes.
- Full extracted text enters the current prompt directly, so vague file questions
  work without matching search keywords. Oversized context returns a clear error.
- Reopening restores attachment chips; chat/project deletion removes their files.
- Verification: **135 Python tests and 7 frontend checks passed**.

File previews and citations follow-up on 2026-10-18:
- Pending, sent and reopened attachment chips open a read-only extracted-text
  preview. No file HTML or scripts are executed. PDF page layout is not shown.
- `Context.sources` assigns numbers to full attachments and retrieved passages;
  the prompt asks for `[1]`-style citations. Source IDs, passage positions and
  document revisions are retained where available.
- `turns.py` streams source metadata for normal chat and Deep think. Sources
  are saved atomically with the answer in `messages.sources`, returned separately
  from canonical message history, and retained in backups/JSON exports.
- `app.js` makes only known reference numbers clickable and lists sources
  supplied to the model. Models may omit inline citations; the list still works.
- Citation previews use saved snapshots, so they survive changes/deletion of
  originals. A separate action opens the current file. Older answers have no
  retrospectively reconstructed sources.
- Verification: **139 Python tests and 7 frontend checks passed**. Headless
  Firefox plus real local Ollama passed file previews, streamed source buttons,
  snapshot display, reopening persisted citations and composer clearing. Browser
  checks also exercised valid/unknown inline references and inspected a screenshot.

Navigation fix on 2026-10-18:
- Chat selection and New chat reveal the chat panel before checking active
  generation/uploads, so visiting Memory/Documents cannot strand the user there.
- Added an explicit Chat sidebar button that returns without reloading a stream.
- Switching conversations while busy explains that Stop/wait is required;
  failed chat loads display an error and preserve the current conversation.
- Verification: **10 frontend checks passed**. Headless Firefox verified Memory,
  Documents, Chat and Reverse switching, opening another chat, and returning
  while generation/upload guards were active, using a temporary database.

Multiple chat deletion on 2026-10-18:
- Added Select chats, per-chat checkboxes, Select all shown, selection counts and
  Delete selected with one confirmation. Scope follows current project/search;
  selecting a row does not open it. Cancel returns to normal navigation.
- Reuses guarded chat deletion endpoints, reports partial failures, retains
  failed selections, and resets the conversation if its chat was removed.
- Stale chat-list responses are ignored; selection prunes to displayed results.
- Verification: **13 frontend checks passed**. Firefox with a temporary database
  verified individual/select-all behavior, mixed selection state, filtered and
  project scope, selected deletions and preservation of unselected chats.

Verification on 2026-10-18:
- Baseline before Stage 2: **115 Python tests and 4 frontend checks passed**.
- With Stage 2: **132 Python tests and 7 frontend checks passed**.
- Real Ollama smoke test with `llama3.2:3b` and `nomic-embed-text`: created and
  indexed a document, generated a correct edit diff, confirmed no mutation before
  Apply, applied as version 2, retrieved its content from a project chat, confirmed
  durable chat saving, and downloaded a backup. Used a temporary database.
- JavaScript syntax, Python compilation and whitespace checks pass.
- Headless Firefox with a temporary database: project navigation, document
  creation, editing and saving, Markdown preview, HTML sanitization, and version
  history passed. Inspected the editor screenshot at a 1280×900 viewport.
- Remaining Stage 1 manual checks: real-model Stop/Regenerate/Deep think and
  visual review of the complete app. Automated regression coverage exists.

### Stage 3 — optional web search

Status: implemented and committed on 2026-10-28 (steps 1–4).

- [x] Configurable search service (SearXNG in Docker on 127.0.0.1:8888) and page reading.
- [x] Source links with results and clear indication when a request accesses the web.
- [x] Keep offline/local chat usable when search is disabled or unavailable.

Implementation notes:
- `websearch.py` asks SearXNG (JSON). `webpage.py` reads one page: public
  addresses only (rechecked after each redirect), the checked IP is pinned
  against DNS rebinding while HTTPS still verifies the name, 10 s / 2 MB /
  HTML-or-text limits, menus skipped, `<main>`/`<article>` preferred.
- `web.py` reads the top 3 pages in parallel, then picks pieces in two rounds
  (words, then meaning) and returns one `kind: "web"` source per page.
- `context.py` adds web sources last and drops them first when the prompt is
  too big. The untrusted-content warning travels with the source list. A failed
  search adds WEB_FAILED to the notes and the `X-Cerberus-Web-Error` header.
- Browser: 🌐 Web box (remembered, off the first time), "Web: N pages" label,
  web source preview with an http(s)-only link, SearXNG address in Settings.
- Verified with real SearXNG, real pages and `llama3.2:3b` (temporary database).

Follow-ups on 2026-10-28 (all committed):
- Redesign: Noto Sans + JetBrains Mono, SVG line icons, user bubbles, pill
  toggles, Settings as grouped cards with switches; `style.css` rebuilt around
  design variables. Checked with headless Firefox screenshots.
- Smart search (`web.plan`): Web means "may search". Small talk, thanks,
  arithmetic, writing tasks and memory questions skip it ("Web: not needed").
  The Helper decides and rewrites follow-ups into queries; a query containing
  numbers not found in the conversation is rejected (a small model once wrote
  its guessed answer into the query). Without a Helper, rules decide and add
  the previous question to short follow-ups. The query is saved with sources.
- Speed, measured on this CPU (llama3.2:3b reads about 75–130 prompt tokens/s):
  the model reading the web text dominated (13–18 s), then embeddings (2.5 s);
  search and page reading take about 2 s. Web pages are now cut into 500-char
  pieces (4 chosen): prompt reading 5–9 s, embeddings 1.2 s, a web answer about
  20 s instead of 24–31 s. DuckDuckGo may answer SearXNG with a CAPTCHA after
  many searches in a row; SearXNG then skips it.
- Known limit: `llama3.2:3b` occasionally ignores correct sources on
  follow-ups; `llama3.1:8b` was reliable but about 2.5× slower.
- Possible next steps: progress messages while searching (prepare() is silent
  for ~5 s), a `web_search` tool for tool models, Stage 4 research mode.

### Stage 4 — research mode

Status: implemented on 2026-10-28 (the user commits changes themselves).

- [x] Plan → search → read sources → generate a sourced report.
- [x] Visible progress, bounded work, cancellation, and saving reports to projects.

Implementation notes:
- `cerberus/research.py` runs fixed steps; the model only writes the plan and
  the report and has no tools. Bounds: 4 searches, 2 new pages each, 2 pieces
  per search (~500 chars), 1500 report tokens. Searches run one after another
  (many at once risk a DuckDuckGo CAPTCHA); pages are read in parallel.
- Plan lines are cleaned, deduplicated, and dropped if they contain numbers
  not found in the conversation (guessed answers); an empty plan searches
  the question itself.
- `POST /research` uses `turns.respond`: Stop, atomic turn saves and sources.
  Only a finished report is saved as a workspace document, with a Sources list.
- `web.pick(limit=)` and `web.as_sources()` are shared with normal Web search.
- Browser: Research pill (exclusive with Deep think), live steps with ✓, and
  an Open report button.
- Real run with `llama3.2:3b`: 4 searches, 8 pages read, 4 sources, report
  saved, about 75 s. Its plan was imprecise and it cited sparingly.

### Stage 5 — agent mode

- Access only selected workspace folders.
- Proposed file edits, command permissions, and an action history.
- Clear review/apply behavior for changes and bounded tool execution.

### Stage 6 — skills and MCP

- Reusable task instructions and configurable external tools.
- Select only relevant tools/instructions so smaller local models keep enough
  context for the actual task.

### Stage 7 — personal workspace

- Notes, todos, reminders, and scheduled tasks.
- Calendar and email integrations later, after the core workflow is reliable.

### Stage 8 — model controls

Part A (Ollama) implemented on 2026-10-28: the Models panel lists installed
models (size, quantization, capabilities, memory use), searches ollama.com
(`cerberus/library.py` reads the search page; there is no official API),
downloads with streamed progress and Cancel (`ollama.pull`), and deletes.
Verified by really downloading and deleting `all-minilm`.
Part B planned: llama.cpp as an alternative engine, managed by Cerberus,
with GGUF models searched and downloaded from Hugging Face (official API).

- Model downloads and local hardware information.
- Side-by-side comparisons of model outputs.
- Hardware-aware settings, guided by testing on the user's machine.

## Starting message for a future session

> Read PLAN.md and README.md. Stages 1 and 2 are implemented locally and remain
> uncommitted. Preserve the existing work, review the remaining smoke checks,
> and help me try workspace documents before discussing stage 3.
