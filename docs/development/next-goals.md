# Cerberus: next goals

[← Roadmap](../roadmap.md)

Updated 29 October 2026. The order is the plan; each goal lists what "done"
means. These are goals, not promises: plans change when users tell us what
they need.

## Done recently

- **Releases and updates:** launcher installs once; Cerberus updates itself from
  Settings → Updates with checksums, and CI checks the Linux build on Fedora,
  Arch and openSUSE.
- **Setup:** one step at a time, ending with a real first answer.
- **Any model, clean answers:** reasoning between think tags goes to "Show
  thinking", tool calls written as text run, and `scripts/check_models.py`
  checks every installed model.
- **Model settings:** context length (with memory estimates and a suggestion
  for this computer) and temperature, per model.

## 1. Keep API keys with their connection

Today one API key is shared by all OpenAI-compatible connections
(`cerberus/engines/openai_api.py`, `current()`). Switching from one cloud
provider to another, or to a local server, can send the previous key to the
new address.

Done when: each saved connection (provider + address) has its own key; switching
never sends another connection's key; changing an address asks for the key
again; existing keys migrate without ever reaching the browser, the database,
exports or backups.

## 2. Edit a message and branch

Change a sent message and get a new answer from that point; the earlier version
stays, reachable with ‹ 1/2 › arrows. Regenerate becomes a branch too.

Done when: editing never loses an answer; the model only sees the branch on
screen; summaries, recaps and exports follow the chosen branch; branches
survive a restart and a backup restore.

## 3. Developer mode

A switch in Settings. Off (the default), Cerberus stays as simple as today.
On, it shows tools for people who want more control:

- **Custom assistants:** saved helpers with their own instructions, model and
  tools, chosen when a chat starts.
- **More model settings:** top-p, repeat penalty, seed and similar.
- **MCP servers** (goal 4) live here.

Done when: switching it off hides everything again without losing it; normal
users never see an option they need developer knowledge for.

## 4. MCP servers (in developer mode)

Connect Model Context Protocol servers so their tools join the calculator, the
time and memory search.

Done when: each server is added deliberately and can be switched off or removed;
every tool run is shown in the chat like built-in tools; a tool that changes
something (writes a file, sends a message) asks first; server credentials stay
with their server (as in goal 1); a server that crashes or hangs never blocks
the chat.

## 5. Recovery

A visible "Restore from backup" in Settings, next to the existing backup.

Done when: a restore checks the backup's version first, can be cancelled, and
keeps the current data if anything fails.

## 6. Clearer download problems

Model and app downloads explain what went wrong: out of disk space, no
permission, connection lost, file in use; each with what to do next.

## Later

- **Dictation:** speak instead of typing, with clear microphone permission and a
  visible recording state.
- **Live HTML/code preview** in a locked-down sandbox, without access to Cerberus.
- **A smaller desktop app:** the Linux download is 253 MB because it bundles a
  browser engine; a shell that uses the system's own (such as Tauri) could make
  every download much smaller.
- **Code signing** for Windows and macOS, so the "unverified app" warnings go away.
- **A local API for other apps**, only with its own authentication and an
  explicit network setting.

## Ways of working

- One goal at a time, each with tests for its "done when".
- Check real models with `scripts/check_models.py` and prompts with
  `scripts/check_prompts.py` whenever answers or prompts change.
- Keep the structure small: `cerberus/` for the app, `launcher/` for installing,
  `static/` for the page, `scripts/` for tools, `tests/` for checks.
