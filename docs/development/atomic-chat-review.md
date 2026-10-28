# Atomic Chat comparison and Cerberus priorities

Review date: 28 October 2026. This is a development assessment, not a security audit or a promise to ship every feature.

## Scope

The reference is Atomic Chat at commit `305b202739e6cbf0127a3c5e4dd60df7c6b5019e`.
Its complete, non-truncated Git tree contains 5,510 tracked files: 2,204 under
`web-app`, 1,281 under `tests`, 1,130 under `docs`, 459 under `src-tauri`,
180 under `extensions`, and 105 under `core`, plus packaging and other files.
I inventoried that tree, extracted 4,811 text/source files, and selectively
reviewed the main feature, engine, packaging, update, and test areas. I did not
read every line, execute upstream code, or independently measure its performance.
Historical documentation and README claims are not proof that a feature works.
No upstream code or artwork was copied into Cerberus.

## What is worth adopting

| Area | Atomic Chat evidence | Cerberus today | Proposed improvement |
| --- | --- | --- | --- |
| Choosing models | Memory-fit indicators, download confirmations, provider-aware context fitting | Model library, local endpoint discovery, managed llama.cpp | Show model size, estimated memory needs, disk needs, and a clear recommended choice before downloading |
| Engine setup | Provider selector and separate engine modules | One selected engine, several presets, one shared API-key setting | Save named connections with their own address, key and model; make switching a single action |
| Downloads | Dedicated disk-error classification and download modules | Existing model download and launcher progress | Explain out-of-space, permission, interrupted connection and locked-file failures with a recovery action |
| Updates | Separate app/backend update hooks and platform packaging | Checksum-verified launcher installs, repair, retained versions | Finish native release verification; add visible installed/latest version and an intentional rollback flow |
| Voice | Voice input and setup components with permission phases | Text/image conversation | Optional local dictation with explicit microphone permission, visible recording state and cancel |
| Artifacts | Dedicated HTML preview using a sandboxed iframe | Markdown documents, revisions and editing proposals | Optional code/HTML preview in a separate sandbox; keep model scripts away from app privileges |
| Integrations | MCP commands, OAuth flow/store, server API modules | Built-in research and tools; OpenAI-compatible client | Add selected MCP connections later; an external OpenAI-compatible server is a separate optional feature |
| Retrieval | Dedicated RAG extension | Existing document/project retrieval, memories and research citations | Improve import feedback and show which sources informed an answer before adding another retrieval stack |
| Verification | Extensive component, contract and platform tests | Python/frontend suites plus release smoke tests | Add a small real desktop journey: install → choose engine → chat → document → restart → update |

Evidence and implementation entry points:

- Model fit: [web-app/src/containers/ModelFitIndicator.tsx](https://github.com/AtomicBot-ai/Atomic-Chat/blob/305b202739e6cbf0127a3c5e4dd60df7c6b5019e/web-app/src/containers/ModelFitIndicator.tsx) and [web-app/src/lib/provider-fit.ts](https://github.com/AtomicBot-ai/Atomic-Chat/blob/305b202739e6cbf0127a3c5e4dd60df7c6b5019e/web-app/src/lib/provider-fit.ts).
- Download failure handling: [src-tauri/src/core/downloads/disk.rs](https://github.com/AtomicBot-ai/Atomic-Chat/blob/305b202739e6cbf0127a3c5e4dd60df7c6b5019e/src-tauri/src/core/downloads/disk.rs).
- Voice permission/setup flow: [web-app/src/containers/VoiceInputToggle.tsx](https://github.com/AtomicBot-ai/Atomic-Chat/blob/305b202739e6cbf0127a3c5e4dd60df7c6b5019e/web-app/src/containers/VoiceInputToggle.tsx).
- HTML preview boundary: [web-app/src/containers/HtmlArtifact.tsx](https://github.com/AtomicBot-ai/Atomic-Chat/blob/305b202739e6cbf0127a3c5e4dd60df7c6b5019e/web-app/src/containers/HtmlArtifact.tsx). Its iframe allows scripts, modals, forms and popups but omits `allow-same-origin`; Cerberus should define its own tighter requirements rather than copy these flags blindly.
- Updates: [web-app/src/hooks/useAppUpdater.ts](https://github.com/AtomicBot-ai/Atomic-Chat/blob/305b202739e6cbf0127a3c5e4dd60df7c6b5019e/web-app/src/hooks/useAppUpdater.ts) and [src-tauri/src/core/updater/commands.rs](https://github.com/AtomicBot-ai/Atomic-Chat/blob/305b202739e6cbf0127a3c5e4dd60df7c6b5019e/src-tauri/src/core/updater/commands.rs).
- MCP session binding: [src-tauri/src/core/mcp/oauth/store.rs](https://github.com/AtomicBot-ai/Atomic-Chat/blob/305b202739e6cbf0127a3c5e4dd60df7c6b5019e/src-tauri/src/core/mcp/oauth/store.rs) stores the server URL alongside tokens to avoid sending a session to a changed host. That is a useful design principle for our own engine credentials.
- Server architecture: [src-tauri/src/core/server/mod.rs](https://github.com/AtomicBot-ai/Atomic-Chat/blob/305b202739e6cbf0127a3c5e4dd60df7c6b5019e/src-tauri/src/core/server/mod.rs). Serving other clients requires a deliberate API/authentication design; connecting Cerberus to an OpenAI-style endpoint does not already provide that server.

## Recommended order

### 1. Release readiness and credential isolation

Finish the Windows fixes, rerun all native release jobs, and review a draft release
before publishing it. Verify a fresh installation has its own empty database and
that updates preserve existing data. Document platform support and signing status
accurately. Existing local build archives must be rebuilt after this license change.

In `cerberus/engines/openai_api.py`, `current()` reads the single
`keys.get("openai_key")` value and `headers()` sends it to the selected endpoint.
`cerberus/core/settings.py` keeps that value when a blank key is submitted.
Consequently a provider/address change can reuse the previous credential.
Replace this with credentials bound to a connection identity and normalized
endpoint. Migrate existing settings without exposing keys in the browser,
database, exports or backups. Acceptance: switching cloud providers or switching
to a local server never sends another connection's key; changing an address
requires an explicit credential decision. This is a focused cross-layer change.

### 2. Make the model page easier

Keep three clear places: **Your models**, **Find models**, and **Connections**.
Give each model one main action: Download, Use, or Start. Put quantization,
context and engine tuning behind Details. Show engine readiness and actionable
errors in the same place. Hardware fit should be described as an estimate and
handle unknown hardware instead of promising that a model will fit.

Acceptance: a new desktop user can connect an already-running local engine or
install a recommended model without understanding API formats. A failed download
shows what happened and how to continue. Medium scope: UI plus hardware/download
integration, rather than a purely cosmetic change.

### 3. Recovery and everyday chat

Add a visible backup/restore flow around existing database snapshot support,
with schema compatibility checks and preservation of the current database on
failure. Add update rollback only after defining how old app versions handle
newer database schemas. Then prioritize conversation search, keyboard navigation,
and response retry/history based on actual user journeys. Conversation branching
is a possible later feature; its behavior was not verified in this upstream review.

Acceptance: a restore can be cancelled safely, a failed restore keeps current
data, and ordinary chat remains easy to navigate. Backup UX is medium scope;
branching changes storage/context semantics and should be a separate project.

### 4. Add optional capabilities one at a time

Local dictation is a useful contained addition. Sandbox previews come next if
users regularly create HTML/code. MCP needs connection permissions, tool visibility,
credential isolation and a way to revoke access before enabling external tools.
A loopback API gateway needs streaming/tool compatibility tests and a separate
authentication/network exposure policy. Each is medium-to-large scope and should
have its own design and acceptance tests.

Native MLX acceleration, custom inference forks, mobile apps and a plugin platform
can wait. They add substantial packaging/support work. Upstream performance claims
were not benchmarked on this machine and should not become Cerberus promises.

## File organization lessons

Atomic Chat's Tauri/Rust, React/TypeScript, core libraries and extension layout
fits its architecture. Cerberus already has domain modules under `cerberus/`,
separate `launcher/`, `packaging/`, `scripts/`, `static/`, and `tests/`.
Keep that smaller structure; changing UI frameworks is not required for a clearer UI.

Useful lessons are explicit engine boundaries, dedicated update/download error
handling, platform capabilities, and tests grouped around user behavior. Keep
release documentation short and separate future ideas from the user guide.
Avoid copying its large historical docs tree or generating many organizational
files before Cerberus needs them.

## License change

Cerberus project-owned code now uses the complete Apache License 2.0 text in
`LICENSE` ([official text](https://www.apache.org/licenses/LICENSE-2.0.txt)), with project attribution in `NOTICE`. New builds include both files
in application/launcher resources and runtime notices. Third-party dependencies
retain their existing licenses, including MIT-licensed vendor libraries.
Changing this checkout does not rewrite earlier MIT releases or their permissions.
