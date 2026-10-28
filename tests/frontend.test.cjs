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
    attachChips: {children: []}, attachStatus: {}, messagesEl: { querySelectorAll: () => [] },
    ensureChat: async () => {}, regenButton: { remove() {} },
    document: { getElementById: () => null }, addUserMessage: () => ({ name: "new question" }),
    addImagesTo() {}, threeHeads: { checked: false }, researchCheck: { checked: false }, sendNormal: async () => null,
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
  assert.equal(labelFor({"X-Cerberus-Mode": "chat", "X-Cerberus-Web": "skipped"}), "Chat, Web: not needed");
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

test("the Research pill sends the question to the research agent", async () => {
  const calls = [];
  const context = sendingContext({
    researchCheck: { checked: true }, threeHeads: { checked: true }, // Research wins
    sendNormal: async (model, url) => { calls.push(url); return null; },
    sendCouncil: async () => { calls.push("council"); return null; },
  });
  vm.runInContext(section("async function send(text,", "// Regenerate: forget"), context);
  await context.send("Compare local LLM runtimes", "model");
  assert.deepEqual(calls, ["/research"]);
});

test("research steps are listed, earlier ones marked done, the report can be opened", () => {
  const made = [];
  function element(tag) {
    const el = { tag, children: [], classList: new Set(), listeners: {},
      get lastElementChild() { return this.children[this.children.length - 1]; },
      append(...items) { this.children.push(...items); }, appendChild(item) { this.children.push(item); },
      before(item) { this.placedBefore = item; },
      querySelector(selector) { return this.children.find(child => child.tag === selector); },
      addEventListener(name, listener) { this.listeners[name] = listener; } };
    el.classList.add = el.classList.add.bind(el.classList);
    made.push(el);
    return el;
  }
  const opened = [];
  const context = vm.createContext({ document: { createElement: element }, openDocumentEditor: id => opened.push(id) });
  vm.runInContext(section("function showProgress(", "// Reads a streamed answer"), context);
  const bubble = { before(box) { this.box = box; } };
  context.showProgress(bubble, { text: "Planning the research…" });
  context.showProgress(bubble, { text: "Reading 3 pages…" });
  context.showProgress(bubble, { text: "Report saved as research-x.md", document_id: 7 });
  const steps = bubble.box.querySelector("ol").children;
  assert.deepEqual(steps.map(step => step.classList.has("done")), [true, true, true]);
  steps[2].children.find(child => child.tag === "button").listeners.click();
  assert.deepEqual(opened, [7]);
});

test("model sizes and download steps are shown in plain words", () => {
  const models = fs.readFileSync("static/models.js", "utf8");
  const context = vm.createContext({});
  const piece = (start, end) => models.slice(models.indexOf(start), models.indexOf(end, models.indexOf(start)));
  vm.runInContext(piece("function formatBytes(", "function tag(") + piece("function downloadStepText(", "async function startDownload("), context);
  assert.equal(context.formatBytes(2013265920), "1.9 GB");
  assert.equal(context.formatBytes(512), "512 bytes");
  assert.equal(context.formatBytes(0), "");
  assert.equal(context.downloadStepText({ status: "pulling manifest" }), "Getting the list of files");
  assert.equal(context.downloadStepText({ status: "pulling 6a0746a1ec1a", completed: 1073741824, total: 2147483648 }),
    "Downloading: 1.0 GB of 2.0 GB (50%)");
  assert.equal(context.downloadStepText({ status: "success" }), "Done");
});

test("library filters and installed sizes", () => {
  const models = fs.readFileSync("static/models.js", "utf8");
  const piece = (start, end) => models.slice(models.indexOf(start), models.indexOf(end, models.indexOf(start)));
  const context = vm.createContext({});
  vm.runInContext(piece("function matchesFilter(", "// Draws the list") + piece("function fullName(", "// One search result") , context);
  const chat = { capabilities: ["tools", "thinking"] };
  const embed = { capabilities: ["embedding"] };
  assert.equal(context.matchesFilter(chat, "all"), true);
  assert.equal(context.matchesFilter(chat, "chat"), true);
  assert.equal(context.matchesFilter(embed, "chat"), false);
  assert.equal(context.matchesFilter(chat, "thinking"), true);
  assert.equal(context.matchesFilter(chat, "vision"), false);
  assert.equal(context.fullName("qwen3", "4b"), "qwen3:4b");
  assert.equal(context.fullName("nomic-embed-text", null), "nomic-embed-text:latest");
});

test("Hugging Face shows the common versions first", () => {
  const models = fs.readFileSync("static/models.js", "utf8");
  const start = models.indexOf("const COMMON_VERSIONS");
  const context = vm.createContext({});
  vm.runInContext(models.slice(start, models.indexOf("// 1234567", start)), context);
  const versions = ["IQ2_M", "Q3_K_M", "Q4_0_4_8", "Q4_K_M", "Q8_0", "F16"].map(version => ({ version }));
  assert.deepEqual(context.commonVersions(versions).map(item => item.version), ["Q3_K_M", "Q4_K_M", "Q8_0"]);
  const unusual = [{ version: "IQ1_S" }, { version: "BF16" }];
  assert.deepEqual(context.commonVersions(unusual), unusual); // nothing common: show all
});

test("a Hugging Face model counts as installed when any of its versions is", () => {
  const models = fs.readFileSync("static/models.js", "utf8");
  const start = models.indexOf("function repoInstalled(");
  const context = vm.createContext({ installedNames: new Set(["hf.co/Bartowski/Qwen2.5-7B-Instruct-GGUF:Q4_K_M", "qwen3:4b"]) });
  vm.runInContext(models.slice(start, models.indexOf("// One Hugging Face model", start)), context);
  assert.equal(context.repoInstalled("bartowski/Qwen2.5-7B-Instruct-GGUF"), true); // capitals don't matter
  assert.equal(context.repoInstalled("bartowski/Qwen2.5-7B-Instruct"), false); // a different repo
  assert.equal(context.repoInstalled("Qwen/Qwen3-4B-GGUF"), false);
});

test("the thinking shimmer stops however an answer ends", async () => {
  for (const ending of ["answer", "error"]) {
    const bubble = { classes: new Set(["pending"]), classList: { remove(name) { bubble.classes.delete(name); } } };
    const context = sendingContext({
      messagesEl: { querySelectorAll: selector => (selector === ".pending" && bubble.classes.has("pending") ? [bubble] : []) },
      sendNormal: async () => { if (ending === "error") throw new Error("Ollama crashed"); return null; },
      addMessage: () => ({}),
    });
    vm.runInContext(section("async function send(text,", "// Regenerate: forget"), context);
    await context.send("hello", "model");
    assert.equal(bubble.classes.has("pending"), false, ending);
  }
});

test("managed llama.cpp sends model paths and restores controls after failure", async () => {
  const setupSource = fs.readFileSync("static/setup.js", "utf8");
  const children = [];
  const details = {
    appendChild: (child) => children.push(child),
    querySelectorAll: () => children.filter((child) => child.click),
  };
  let request;
  const context = vm.createContext({
    document: { createElement: () => ({ setAttribute() {} }) },
    makeBox: (cls, text) => ({ textContent: text }),
    setupButton: (text, click) => ({ textContent: text, click }),
    setupDisclosure: () => ({ root: {}, body: { appendChild() {} } }),
    setupField: (label, input) => input,
    setupBusy: false,
    fetch: async (url, options) => { request = { url, body: JSON.parse(options.body) }; return { ok: false }; },
    responseError: async () => "Port is in use",
    afterEngineChange: async () => assert.fail("must keep the error visible"),
  });
  vm.runInContext(setupSource.slice(setupSource.indexOf("function managedLlamaDetails("),
    setupSource.indexOf("// Ollama: what it was before")), context);
  context.managedLlamaDetails(details, { binary: "llama-server", model: "/my model.gguf", port: "8123", owned: false });
  const button = children.find((child) => child.textContent === "Start with Cerberus");
  await button.click();
  assert.equal(request.url, "/setup/llamacpp/start");
  assert.deepEqual(request.body, { binary: "llama-server", model: "/my model.gguf", port: 8123 });
  assert.equal(children.at(-1).textContent, "Port is in use");
  assert.equal(button.disabled, false);
  assert.equal(context.setupBusy, false);
});

test("managed llama.cpp offers stop for an owned server and refreshes after stopping", async () => {
  const setupSource = fs.readFileSync("static/setup.js", "utf8");
  const children = [];
  let refreshed = false;
  let endpoint;
  const context = vm.createContext({
    document: { createElement: () => ({ setAttribute() {} }) },
    makeBox: (cls, text) => ({ textContent: text }),
    setupButton: (text, click) => ({ textContent: text, click }),
    setupDisclosure: () => ({ root: {}, body: { appendChild() {} } }),
    setupField: (label, input) => input,
    setupBusy: false,
    fetch: async (url) => { endpoint = url; return { ok: true }; },
    afterEngineChange: async () => { refreshed = true; },
  });
  vm.runInContext(setupSource.slice(setupSource.indexOf("function managedLlamaDetails("),
    setupSource.indexOf("// Ollama: what it was before")), context);
  const details = { appendChild: (child) => children.push(child), querySelectorAll: () => children.filter((child) => child.click) };
  context.managedLlamaDetails(details, { binary: "llama-server", model: "/a.gguf", port: "8080", owned: true, enabled: true });
  assert(!children.some((child) => child.textContent === "Start with Cerberus"));
  await children.find((child) => child.textContent === "Stop & disable automatic start").click();
  assert.equal(endpoint, "/setup/llamacpp/stop");
  assert(refreshed);
  assert.equal(context.setupBusy, false);
});

// A small DOM for exercising the real setup builders and their event handlers.
function setupHarness() {
  class Element {
    constructor(tag) { this.tagName = tag; this.children = []; this.attributes = {}; this.events = {}; this.open = false; }
    set textContent(value) { this.text = value; this.children = []; }
    get textContent() { return (this.text || "") + this.children.map((child) => child.textContent).join(""); }
    set innerHTML(value) { this.children = []; this.text = ""; }
    append(...children) { this.children.push(...children); }
    appendChild(child) { this.append(child); return child; }
    setAttribute(name, value) { this.attributes[name] = value; }
    addEventListener(name, callback) { this.events[name] = callback; }
    querySelectorAll(tag) { return walk(this).filter((child) => child !== this && child.tagName === tag); }
  }
  function walk(node) { return [node, ...node.children.flatMap(walk)]; }
  const context = vm.createContext({
    document: { createElement: (tag) => new Element(tag) },
    Option: class extends Element { constructor(text, value) { super("option"); this.textContent = text; this.value = value; } },
    makeBox: (cls, text) => { const node = new Element("div"); node.className = cls; node.textContent = text; return node; },
    URL, setupBusy: false,
  });
  const setupSource = fs.readFileSync("static/setup.js", "utf8");
  vm.runInContext(setupSource.slice(setupSource.indexOf("// ---------- Building blocks"),
    setupSource.indexOf("// ---------- Buttons, and opening")), context);
  const presets = {
    huggingface: { name: "Hugging Face (cloud)", key: true, key_help: "Enter a token", url: "https://router.huggingface.co/v1" },
    openai: { name: "OpenAI", key: true, key_help: "Enter a key", url: "https://api.openai.com/v1" },
    groq: { name: "Groq" }, openrouter: { name: "OpenRouter" },
    llamacpp: { name: "llama.cpp", key: false, url: "http://127.0.0.1:8080/v1" },
    lmstudio: { name: "LM Studio" }, jan: { name: "Jan" }, custom: { name: "Other", url: "", key_help: "Custom server" },
  };
  const state = {
    engine: { running: true, kind: "ollama", name: "Ollama" }, ollama: { running: true },
    chat_models: ["local-model"], embed_installed: false,
    engines: { engine: "ollama", presets, openai: { preset: "openai", url: presets.openai.url, key_set: false },
      llamacpp: { binary: "llama-server", model: "/a.gguf", port: "8123", enabled: true, owned: false } },
  };
  return { context, state, walk };
}

test("setup groups local and cloud choices and keeps cloud addresses under connection settings", () => {
  const { context, state, walk } = setupHarness();
  const card = context.engineStep(state);
  const select = () => walk(card).find((node) => node.tagName === "select");
  assert.equal(select().value, "ollama");
  assert.deepEqual(select().children.map((node) => node.value), ["ollama", "llamacpp", "lmstudio", "jan"]);
  const cloud = walk(card).find((node) => node.tagName === "button" && node.textContent.includes("Cloud service"));
  cloud.events.click();
  assert.equal(cloud.attributes["aria-pressed"], "true");
  assert.deepEqual(select().children.map((node) => node.value), ["huggingface", "openai", "groq", "openrouter"]);
  const connection = walk(card).find((node) => node.tagName === "details");
  assert.equal(connection.open, false);
  assert(walk(connection).some((node) => node.type === "url"));
  assert(walk(card).some((node) => node.type === "password" && !walk(connection).includes(node)));
  assert(walk(card).some((node) => node.className === "hint engine-cloud" && !node.hidden));
});

test("llama.cpp puts the model first and folds executable, port and external server settings", () => {
  const { context, state, walk } = setupHarness();
  state.engines.openai.preset = "llamacpp";
  state.engines.openai.url = "http://127.0.0.1:8123/v1";
  state.engines.engine = "openai";
  state.engine = { running: false, error: "Offline" };
  const card = context.engineStep(state);
  const advanced = walk(card).find((node) => node.tagName === "details" && node.children[0].textContent.includes("Advanced"));
  const external = walk(card).find((node) => node.tagName === "details" && node.children[0].textContent.includes("existing server"));
  assert.equal(advanced.open, false);
  assert.equal(external.open, false);
  assert(walk(advanced).some((node) => node.value === "llama-server"));
  assert(walk(advanced).some((node) => node.value === "8123"));
  const model = walk(card).find((node) => node.value === "/a.gguf");
  assert(model && !walk(advanced).includes(model) && !walk(external).includes(model));
});

test("missing optional embeddings do not mark an available chat model as unfinished", () => {
  const { context, state, walk } = setupHarness();
  const card = context.modelsStep(state);
  assert(walk(card).some((node) => node.className === "setup-badge ok"));
  const search = walk(card).find((node) => node.tagName === "details");
  assert.equal(search.open, false);
  assert(search.textContent.includes("Better document search"));
});

test("Docs and Memory open independent screens and load only their own content", () => {
  const html = fs.readFileSync("static/index.html", "utf8");
  const documentsPanel = html.match(/<section id="panel-documents"[^>]*>([\s\S]*?)<\/section>/)[1];
  const memoryPanel = html.match(/<section id="panel-memory"[^>]*>([\s\S]*?)<\/section>/)[1];
  assert(documentsPanel.includes('id="document-list"'));
  assert(documentsPanel.includes('id="document-file"'));
  assert(documentsPanel.includes('id="new-document"'));
  assert(!documentsPanel.includes('id="memory-list"'));
  assert(memoryPanel.includes('id="memory-list"'));
  assert(memoryPanel.includes('id="memory-add"'));
  assert(!memoryPanel.includes('id="document-list"'));
  assert(!html.includes("data-tab="));
  function element(id, dataset = {}) {
    const classes = new Set();
    const attrs = {};
    return { id, dataset, classes, attrs, events: {},
      classList: { toggle: (name, selected) => selected ? classes.add(name) : classes.delete(name) },
      addEventListener(name, callback) { this.events[name] = callback; },
      setAttribute(name, value) { attrs[name] = value; },
      removeAttribute(name) { delete attrs[name]; },
    };
  }
  const names = ["chat", "documents", "memory", "models"];
  const buttons = names.map((name) => element(name, { feature: name }));
  const panels = names.map((name) => element("panel-" + name));
  let memoriesLoaded = 0, documentsLoaded = 0;
  const context = vm.createContext({
    document: { querySelectorAll: (selector) => ({ "[data-feature]": buttons, ".panel": panels })[selector] },
    loadMemories: () => memoriesLoaded++, loadDocuments: () => documentsLoaded++, loadModelsPanel() {},
  });
  vm.runInContext(fs.readFileSync("static/features.js", "utf8"), context);
  const active = (nodes) => nodes.filter((node) => node.classes.has("active")).map((node) => node.id);
  buttons[1].events.click();
  assert.deepEqual(active(buttons), ["documents"]);
  assert.deepEqual(active(panels), ["panel-documents"]);
  assert.equal(buttons[1].attrs["aria-current"], "page");
  assert.equal(documentsLoaded, 1);
  assert.equal(memoriesLoaded, 0);
  buttons[2].events.click();
  assert.deepEqual(active(buttons), ["memory"]);
  assert.deepEqual(active(panels), ["panel-memory"]);
  assert.equal(buttons[1].attrs["aria-current"], undefined);
  assert.equal(memoriesLoaded, 1);
  assert.equal(documentsLoaded, 1);
  context.showFeature("chat");
  assert.deepEqual(active(buttons), ["chat"]);
  assert.deepEqual(active(panels), ["panel-chat"]);
  buttons[1].events.click();
  assert.equal(documentsLoaded, 2);
  assert.equal(memoriesLoaded, 1);
});

function modelsHarness(savedSource = null) {
  class Element {
    constructor() { this.children = []; this.events = {}; this.dataset = {}; this.attrs = {}; this.hidden = false; this.open = false;
      this.classList = { toggle() {}, add() {} }; }
    append(...children) { this.children.push(...children); }
    appendChild(child) { this.children.push(child); }
    addEventListener(name, callback) { this.events[name] = callback; }
    setAttribute(name, value) { this.attrs[name] = value; }
  }
  const elements = new Map();
  const get = (id) => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  get("source-huggingface").hidden = true;
  get("source-local").hidden = true;
  const views = ["installed", "discover"].map((view) => { const el = new Element(); el.dataset.modelView = view; return el; });
  const sources = ["local", "ollama", "huggingface"].map((source) => { const el = new Element(); el.dataset.source = source; return el; });
  let libraryCalls = 0, hfCalls = 0, installedCalls = 0;
  const context = vm.createContext({
    document: { getElementById: get, createElement: () => new Element(), querySelectorAll: selector =>
      selector === "[data-model-view]" ? views : selector === "#model-source [data-source]" ? sources : [] },
    localStorage: { getItem: () => savedSource, setItem() {} },
    currentEngine: { kind: "ollama", name: "Ollama" }, controller: null, attachmentUploads: 0,
  });
  vm.runInContext(fs.readFileSync("static/models.js", "utf8"), context);
  context.loadLibrary = () => { libraryCalls++; vm.runInContext("libraryLoaded = true", context); };
  context.loadHuggingFace = () => { hfCalls++; vm.runInContext("hfLoaded = true", context); };
  context.loadInstalledModels = () => { installedCalls++; };
  return { context, get, views, counts: () => ({ libraryCalls, hfCalls, installedCalls }) };
}

test("Your models stays local and libraries load only when opened, including a remembered source", () => {
  const { context, get, views, counts } = modelsHarness("huggingface");
  context.loadModelsPanel();
  assert.deepEqual(counts(), { libraryCalls: 0, hfCalls: 0, installedCalls: 1 });
  views[1].events.click();
  assert.equal(get("models-installed-view").hidden, true);
  assert.equal(get("models-discover-view").hidden, false);
  assert.equal(views[1].attrs["aria-pressed"], "true");
  assert.equal(counts().hfCalls, 1);
  context.showSource("ollama");
  assert.equal(counts().libraryCalls, 1);
  views[0].events.click();
  views[1].events.click();
  assert.equal(counts().libraryCalls, 1);
  assert.equal(counts().hfCalls, 1);
});

test("Use in chat selects the model through the existing change handler and guards active answers", async () => {
  const { context } = modelsHarness();
  let changes = 0, loads = 0, opened;
  context.loadModels = async () => { loads++; };
  context.modelSelect = { value: "old", options: [{ value: "chat-model" }], dispatchEvent(event) { assert.equal(event.type, "change"); changes++; } };
  context.Event = class { constructor(type) { this.type = type; } };
  context.showFeature = (name) => { opened = name; };
  await context.useInstalledModel("chat-model");
  assert.equal(context.modelSelect.value, "chat-model");
  assert.equal(changes, 1);
  assert.equal(opened, "chat");
  context.controller = {};
  await context.useInstalledModel("other-model");
  assert.equal(changes, 1);
  assert.equal(loads, 1);
  context.controller = null;
  context.loadModels = async () => { context.controller = {}; };
  await context.useInstalledModel("other-model");
  assert.equal(changes, 1);
});

test("installed cards offer chat only for chat models on Ollama and fold technical details", () => {
  const { context } = modelsHarness();
  const walk = node => [node, ...node.children.flatMap(walk)];
  const model = { name: "chat-model", capabilities: ["completion", "vision"], size: 1024, parameters: "3B", quantization: "Q4_K_M" };
  const card = context.installedRow(model);
  assert(walk(card).some(node => node.textContent === "Use in chat"));
  assert(walk(card).some(node => node.textContent === "Reads images"));
  const technical = walk(card).find(node => node.className === "model-technical");
  assert.equal(technical.open, false);
  assert(!walk(context.installedRow({ ...model, capabilities: ["embedding"] })).some(node => node.textContent === "Use in chat"));
  context.currentEngine = { kind: "openai", name: "Other engine" };
  assert(!walk(context.installedRow(model)).some(node => node.textContent === "Use in chat"));
});

test("Local apps loads without querying an online library and refresh shows newly available models", async () => {
  const { context, get, counts } = modelsHarness();
  let scans = 0;
  context.fetch = async url => {
    assert.equal(url, "/models/local");
    scans++;
    return { ok: true, json: async () => ({ engines: [{ name: "LM Studio", preset: "lmstudio", url: "http://127.0.0.1:1234/v1", models: scans === 1 ? [] : ["local-chat"] }] }) };
  };
  context.showModelsView("discover");
  const initial = counts().libraryCalls;
  context.showSource("local");
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(scans, 1);
  assert(get("local-models-status").textContent.includes("no models"));
  assert.equal(counts().libraryCalls, initial);
  assert.equal(get("source-ollama").hidden, true);
  await get("local-models-refresh").events.click();
  assert.equal(scans, 2);
  assert(get("local-models-status").textContent.includes("1 model available"));
  assert.equal(get("local-models-results").children.length, 1);
  assert.equal(get("local-models-refresh").disabled, false);
});

test("local model selection connects its engine before selecting the model, and guards active chats", async () => {
  const { context } = modelsHarness();
  let request, selected, changes = 0;
  context.fetch = async (url, options) => { request = { url, body: JSON.parse(options.body) }; return { ok: true, json: async () => ({ ok: true }) }; };
  context.loadModels = async () => {};
  context.modelSelect = { options: [{ value: "my-model" }], dispatchEvent() { changes++; } };
  context.Event = class {};
  context.showFeature = name => { selected = name; };
  const engine = { name: "Jan", preset: "jan", url: "http://127.0.0.1:1337/v1" };
  const row = context.localModelRow(engine, "my-model");
  const use = row.children[1];
  context.controller = {};
  await use.events.click();
  assert.equal(request, undefined);
  context.controller = null;
  await use.events.click();
  assert.equal(request.url, "/setup/engine");
  assert.deepEqual(request.body, { engine: "openai", preset: "jan", url: engine.url, key: "" });
  assert.equal(context.modelSelect.value, "my-model");
  assert.equal(changes, 1);
  assert.equal(selected, "chat");
  assert.equal(use.disabled, false);
});
