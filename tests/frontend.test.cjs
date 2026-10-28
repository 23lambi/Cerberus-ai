// Focused checks of streaming and chat state, without a browser dependency.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync("static/app.js", "utf8");
function section(start, end) {
  return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
}

test("NDJSON preserves split UTF-8 and a final line without a newline", async () => {
  const text = '{"type":"content","text":"héllo"}\n{"type":"done","saved":true}';
  const bytes = new TextEncoder().encode(text);
  let index = 0;
  const received = [];
  const context = vm.createContext({ TextDecoder });
  vm.runInContext(section("async function readEvents(", "// The fold-out box"), context);
  const response = { body: { getReader: () => ({ read: async () =>
    index < bytes.length ? { done: false, value: bytes.slice(index, ++index) } : { done: true }
  }) } };
  await context.readEvents(response, (event) => received.push(event));
  assert.equal(received[0].text, "héllo");
  assert.equal(received[1].saved, true);
});

test("Stop retries when chat creation or run registration is still pending", async () => {
  let calls = 0;
  const context = vm.createContext({
    controller: {}, currentChatId: null, sendButton: {}, attachStatus: {},
    responseError: async () => "error",
    setTimeout: (callback) => { context.currentChatId = 7; callback(); },
    fetch: async () => ({ ok: true, json: async () => ({ stopping: ++calls === 2 }) }),
  });
  vm.runInContext(section("const pause =", "async function committedChat("), context);
  await context.stopAnswer();
  assert.equal(calls, 2);
  assert.equal(context.sendButton.textContent, "Stopping...");
});

function sendingContext(overrides = {}) {
  const previousUser = { name: "previous saved question" };
  const history = [{ role: "user", content: "previous" }, { role: "assistant", content: "answer" }];
  return vm.createContext({
    controller: null, AbortController, sendButton: {}, lastUserEl: previousUser, history,
    attachChips: {children: []}, attachStatus: {},
    ensureChat: async () => {}, regenButton: { remove() {} },
    document: { getElementById: () => null }, addUserMessage: () => ({ name: "new question" }),
    addImagesTo() {}, threeHeads: { checked: false }, sendNormal: async () => null,
    committedChat: async () => ({ messages: history.slice(0, 2) }),
    showRegenerate() {}, makeTitle: async () => {}, loadChats() {}, ...overrides,
  });
}

test("a rejected new question leaves Regenerate pointing at the saved question", async () => {
  const context = sendingContext();
  const previous = context.lastUserEl;
  vm.runInContext(section("async function send(text,", "// Regenerate: forget"), context);
  await context.send("new question", "model");
  assert.equal(context.lastUserEl, previous);
  assert.equal(context.history.length, 2);
  assert.equal(context.controller, null);
});

test("double submit creates only one turn while ensureChat is pending", async () => {
  let release;
  let creations = 0;
  const waiting = new Promise((resolve) => { release = resolve; });
  const context = sendingContext({ ensureChat: async () => { creations++; await waiting; } });
  vm.runInContext(section("async function send(text,", "// Regenerate: forget"), context);
  const first = context.send("first", "model");
  await context.send("second", "model");
  assert.equal(creations, 1);
  release();
  await first;
});

function workspaceContext(fetch) {
  const elements = new Map();
  function element() {
    return {
      value: "", textContent: "", hidden: false, open: false, disabled: false,
      listeners: {}, children: [],
      addEventListener(name, listener) { this.listeners[name] = listener; },
      appendChild(child) { this.children.push(child); },
      replaceChildren(...children) { this.children = children; },
      add(child) { this.children.push(child); },
      showModal() { this.open = true; }, close() { this.open = false; },
      querySelectorAll() { return [...elements.values()]; },
    };
  }
  const context = vm.createContext({
    fetch, currentProject: {id: 7, name: "Project seven"},
    document: {
      getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
      createElement: element,
    },
    window: {addEventListener() {}},
    Option: function(text, value) { this.text = text; this.value = value; },
    responseError: async response => (await response.json()).detail,
    confirm: () => false,
  });
  vm.runInContext(fs.readFileSync("static/documents.js", "utf8"), context);
  const click = id => elements.get(id).listeners.click();
  return {context, elements, click};
}

test("saving an answer retains project scope and blocks a duplicate save", async () => {
  let release, writes = 0, saved;
  const pending = new Promise(resolve => { release = resolve; });
  const {context, elements, click} = workspaceContext(async (url, options) => {
    if (url === "/documents/workspace") {
      writes++;
      saved = JSON.parse(options.body);
      await pending;
      return {ok: true, json: async () => ({...saved, id: 9, revision: 1})};
    }
    return {ok: true, json: async () => ({versions: [], documents: []})};
  });
  await context.openDocumentEditor(null, "An answer worth keeping");
  const first = click("editor-save");
  await click("editor-save");
  assert.equal(writes, 1);
  assert.equal(saved.project_id, 7);
  assert.equal(saved.content, "An answer worth keeping");
  release(); await first;
  assert.match(elements.get("editor-status").textContent, /Saved version 1/);
});

test("AI proposal requires saved content and editing invalidates a reviewed proposal", async () => {
  let proposals = 0;
  const doc = {id: 9, name: "notes.md", content: "Saved text", project_id: 7, revision: 1, editable: true};
  const {context, elements, click} = workspaceContext(async url => {
    if (url.endsWith("/proposals")) {
      proposals++;
      return {ok: true, json: async () => ({id: 2, content: "Proposed text", diff: "-Saved\n+Proposed"})};
    }
    return {ok: true, json: async () => url.endsWith("/versions") ? {versions: []} : doc};
  });
  await context.openDocumentEditor(9);
  elements.get("editor-content").value = "Unsaved work";
  await click("editor-propose");
  assert.equal(proposals, 0);
  elements.get("editor-content").value = doc.content;
  context.document.getElementById("model").value = "small:3b";
  await click("editor-propose");
  assert.equal(proposals, 1);
  assert.equal(elements.get("editor-proposal").hidden, false);
  assert.equal(elements.get("editor-content").value, "Saved text");
  elements.get("editor-content").value = "A new manual change";
  elements.get("editor-content").listeners.input();
  assert.equal(elements.get("editor-proposal").hidden, true);
  await click("editor-apply");
  assert.match(elements.get("editor-status").textContent, /fresh proposal/);
});

test("closing the editor preserves unsaved work when discard is declined", async () => {
  const {context, elements, click} = workspaceContext(async () => ({ok: true, json: async () => ({versions: []})}));
  await context.openDocumentEditor(null, "Unsaved answer");
  click("editor-close");
  assert.equal(elements.get("document-editor").open, true);
  assert.equal(elements.get("editor-content").value, "Unsaved answer");
});

test("returning from Memory to an answering chat switches panels without reloading its stream", async () => {
  const context = vm.createContext({
    controller: {}, currentChatId: 7, attachStatus: {},
    showFeature(name) { context.panel = name; },
    fetch() { throw new Error("An active stream must not be reloaded"); },
  });
  vm.runInContext(section("async function openChat(", "// An empty chat."), context);
  await context.openChat(7);
  assert.equal(context.panel, "chat");
  assert.equal(context.currentChatId, 7);
  await context.openChat(8);
  assert.equal(context.panel, "chat");
  assert.match(context.attachStatus.textContent, /Stop the current answer/);
});

test("New chat returns to the current conversation while an upload is running", () => {
  const context = vm.createContext({
    controller: null, attachmentUploads: true, currentChatId: 7,
    showFeature(name) { context.panel = name; },
  });
  vm.runInContext(section("function newChat()", "// ---------- Home screen"), context);
  context.newChat();
  assert.equal(context.panel, "chat");
  assert.equal(context.currentChatId, 7);
});

test("failed chat navigation returns to Chat and shows the connection error", async () => {
  const context = vm.createContext({
    controller: null, currentChatId: 7, attachStatus: {}, recapChat() {},
    showFeature(name) { context.panel = name; },
    fetch: async () => { throw new Error("offline"); },
  });
  vm.runInContext(section("async function openChat(", "// An empty chat."), context);
  await context.openChat(8);
  assert.equal(context.panel, "chat");
  assert.equal(context.currentChatId, 7);
  assert.match(context.attachStatus.textContent, /Could not open the chat/);
});

function bulkDeleteContext(overrides = {}) {
  const status = {};
  const context = vm.createContext({
    deletingChats: false, selectingChats: true, selectedChatIds: new Set([1, 2]),
    currentChatId: 9, controller: null, attachmentUploads: false,
    document: {getElementById: () => status},
    confirm: () => true, updateChatSelection() {}, loadChats: async () => {}, loadProjects: async () => {},
    responseError: async () => "This chat is still answering.",
    fetch: async () => ({ok: true}), ...overrides,
  });
  vm.runInContext(section("async function deleteSelectedChats()", "// Draws the chat list"), context);
  return {context, status};
}

test("bulk delete keeps failed chats selected and reports partial success", async () => {
  const calls = [];
  const {context, status} = bulkDeleteContext({fetch: async url => {
    calls.push(url);
    return {ok: url === "/chats/1"};
  }});
  await context.deleteSelectedChats();
  assert.deepEqual(calls, ["/chats/1", "/chats/2"]);
  assert.deepEqual([...context.selectedChatIds], [2]);
  assert.equal(context.deletingChats, false);
  assert.equal(context.selectingChats, true);
  assert.match(status.textContent, /Deleted 1 chat\(s\).*1 failed/);
});

test("bulk delete does nothing when confirmation is cancelled", async () => {
  const {context} = bulkDeleteContext({confirm: () => false, fetch() { throw new Error("Unexpected deletion"); }});
  await context.deleteSelectedChats();
  assert.equal(context.selectedChatIds.size, 2);
});

test("bulk delete protects the current answering chat before deleting anything", async () => {
  const {context, status} = bulkDeleteContext({currentChatId: 1, controller: {}, fetch() { throw new Error("Unexpected deletion"); }});
  await context.deleteSelectedChats();
  assert.match(status.textContent, /Stop the answer/);
  assert.equal(context.selectedChatIds.size, 2);
});

function memoryContext(fetch) {
  const elements = new Map();
  const context = vm.createContext({
    fetch,
    responseError: async response => (await response.json()).detail,
    document: {
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, {value: "", textContent: "", listeners: {},
          addEventListener(name, listener) { this.listeners[name] = listener; }});
        return elements.get(id);
      },
    },
  });
  vm.runInContext(fs.readFileSync("static/memory.js", "utf8"), context);
  const submit = () => elements.get("memory-add").listeners.submit({preventDefault() {}});
  return {elements, submit};
}

test("a failed memory save keeps the typed text and explains why", async () => {
  const {elements, submit} = memoryContext(async () => ({ok: false, json: async () => ({detail: "Server error"})}));
  elements.get("memory-input").value = "I like tea";
  await submit();
  assert.equal(elements.get("memory-input").value, "I like tea");
  assert.equal(elements.get("memory-status").textContent, "Server error");
});

test("an unreachable server is reported instead of failing silently", async () => {
  const {elements, submit} = memoryContext(async () => { throw new TypeError("Failed to fetch"); });
  elements.get("memory-input").value = "I like tea";
  await submit();
  assert.equal(elements.get("memory-input").value, "I like tea");
  assert.match(elements.get("memory-status").textContent, /Could not reach Cerberus/);
});

function labelFor(headers) {
  const context = vm.createContext({ MODE_NAMES: { chat: "Chat", memory: "Memory" } });
  vm.runInContext(section("function sourceLabels(", "// Under an answer:"), context);
  // Like the browser's Headers: a missing header is null (a Map would say undefined).
  return context.replyLabel({ get: name => headers[name] ?? null });
}

test("the answer label says when the web was used, also when nothing was found", () => {
  assert.equal(labelFor({"X-Cerberus-Mode": "chat"}), "Chat");
  assert.equal(labelFor({"X-Cerberus-Mode": "chat", "X-Cerberus-Web": "3"}), "Chat, Web: 3 pages");
  assert.equal(labelFor({"X-Cerberus-Mode": "chat", "X-Cerberus-Web": "1"}), "Chat, Web: 1 page");
  assert.equal(labelFor({"X-Cerberus-Mode": "chat", "X-Cerberus-Web": "0"}), "Chat, Web: no pages");
});

test("a web source opens its page in a new tab instead of a document", async () => {
  const {context, elements} = workspaceContext(async () => { throw new Error("Snapshots need no request"); });
  await context.openFilePreview(undefined, {number: 1, name: "Zebra facts (animals.example)",
    text: "Stripes are unique.", kind: "web", url: "https://animals.example/zebra"});
  assert.equal(elements.get("file-preview-text").textContent, "Stripes are unique.");
  assert.equal(elements.get("file-preview-link").hidden, false);
  assert.equal(elements.get("file-preview-link").href, "https://animals.example/zebra");
  assert.equal(elements.get("file-preview-current").hidden, true);
  assert.match(elements.get("file-preview-status").textContent, /web page/);
});

test("a saved source can never turn a link into code", async () => {
  const {context, elements} = workspaceContext(async () => { throw new Error("Snapshots need no request"); });
  await context.openFilePreview(undefined, {number: 1, name: "Evil", text: "x", kind: "web",
    url: "javascript:alert(document.cookie)"});
  assert.equal(elements.get("file-preview-link").hidden, true);
  assert.equal(elements.get("file-preview-link").href, "#");
});
