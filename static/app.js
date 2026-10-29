// The chat: sending messages, showing streamed answers, and the chat list.
// The other files (memory.js, projects.js, ...) handle the other panels.
// All <script> files on a page share one global space, so the functions
// and variables here can be used by the other files too.

// ---------- The elements we work with ----------

const form = document.getElementById("chat-form");
const input = document.getElementById("input");
const messagesEl = document.getElementById("messages");
const modelSelect = document.getElementById("model");
const threeHeads = document.getElementById("three-heads");
const researchCheck = document.getElementById("research");
const thinkToggle = document.getElementById("think-toggle");
const thinkCheck = document.getElementById("think");
const toolsToggle = document.getElementById("tools-toggle");
const toolsCheck = document.getElementById("tools");
const webCheck = document.getElementById("web");
const chatList = document.getElementById("chat-list");
const chatSearch = document.getElementById("chat-search");
const newChatButton = document.getElementById("new-chat");
const sendButton = document.getElementById("send");
const attachButton = document.getElementById("attach");
const attachStatus = document.getElementById("attach-status");

// NEW: the row of file chips, created here and placed right above the message box.
const attachChips = document.createElement("div");
attachChips.id = "attach-chips";
form.before(attachChips);

// The row of images waiting to be sent, right above the message box.
const imageChips = document.createElement("div");
imageChips.id = "image-chips";
form.before(imageChips);

const imageButton = document.getElementById("image");
const imageFile = document.getElementById("image-file");

// The Regenerate button. There is only one: after each answer it moves to
// the bottom of the chat (appendChild moves an element that already exists).
const regenButton = document.createElement("button");
regenButton.type = "button";
regenButton.id = "regenerate";
regenButton.textContent = "↻ Regenerate";
regenButton.addEventListener("click", () => regenerate());

// The server sends "chat" or "memory"; this is what the user sees.
const MODE_NAMES = {
  chat: "Chat",
  memory: "Memory",
};

const STEP_LABELS = {
  draft: "Draft",
  review: "Review",
};

// ---------- State: what the page remembers while it's open ----------

let history = []; // the messages of the open chat: [{ role, content }, ...]
let currentChatId = null; // null = a new chat that isn't saved yet
let currentProject = null; // null = not inside a project
// The "remote control" that cancels the running request. null = nothing running.
let controller = null;
// The newest "You: ..." message on screen. Regenerate removes it and
// everything after it.
let lastUserEl = null;
let thinkingModels = new Set(); // the models that can think, from /models
let toolModels = new Set(); // the models that can use tools, from /models
let visionModels = new Set(); // the models that can see images, from /models
let pendingImages = []; // images waiting to be sent, as base64 text
let eyesReady = false; // Eyes is on, so every chat model can take images

// ---------- Helpers ----------

// The server tells us in headers what it found, like X-Cerberus-Memories: 2.
// This turns them into labels like ["2 memories", "1 document part"].
function sourceLabels(headers) {
  const kinds = [
    ["X-Cerberus-Memories", "memory", "memories"],
    ["X-Cerberus-Documents", "document part", "document parts"],
    ["X-Cerberus-Chats", "old chat message", "old chat messages"],
  ];
  const labels = [];
  // [header, one, many] unpacks each inner list into three variables.
  for (const [header, one, many] of kinds) {
    const count = Number(headers.get(header) || 0);
    if (count) labels.push(count + " " + (count === 1 ? one : many));
  }
  return labels;
}

// The label shown with an answer, like "Memory, 2 memories".
// Normal answers and Deep think both use it.
function replyLabel(headers) {
  const mode = MODE_NAMES[headers.get("X-Cerberus-Mode")] || "Chat";
  // [mode, ...list] = a new list: mode first, then everything in list.
  const labels = [mode, ...sourceLabels(headers)];
  // The server only sends X-Cerberus-Web when the web was asked, even
  // with 0 pages found, so you always see that a request went online.
  const web = headers.get("X-Cerberus-Web");
  if (web === "skipped") {
    // Web was allowed, but this message didn't need it (like "hello").
    labels.push("Web: not needed");
  } else if (web !== null) {
    const pages = Number(web);
    labels.push("Web: " + (pages ? pages + (pages === 1 ? " page" : " pages") : "no pages"));
  }
  return labels.join(", ");
}

// Under an answer: why the web search failed (SearXNG not running...).
// The answer itself still comes, from what the model already knows.
function showWebError(headers, el) {
  const error = headers.get("X-Cerberus-Web-Error");
  if (error) el.after(makeBox("hint", "Web search failed: " + error));
}

// Adds a plain-text message at the bottom of the chat and returns it,
// so the caller can change its text later.
function addMessage(text) {
  const div = document.createElement("div");
  div.className = "message";
  div.textContent = text; // textContent, never innerHTML: text can't become code
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight; // scroll to the bottom
  return div;
}

// Your own message: a bubble on the right (see .message.user in style.css).
function addUserMessage(text) {
  const div = addMessage(text);
  div.classList.add("user");
  return div;
}

// The line above an answer: the logo, "Cerberus", and the details in grey.
// "Cerberus (Chat, Web: 2 pages):" -> Cerberus  Chat · Web: 2 pages
function replyHead(label) {
  const match = /^(.*?)(?: \((.*)\))?:$/.exec(label) || [label, label, ""];
  const head = document.createElement("div");
  head.className = "reply-head";
  // innerHTML is fine here: a fixed piece of HTML, nothing from the model.
  head.innerHTML = '<svg class="avatar"><use href="#i-logo"/></svg>';
  const name = document.createElement("strong");
  name.textContent = match[1];
  head.appendChild(name);
  if (match[2]) {
    const meta = document.createElement("span");
    meta.className = "reply-meta";
    meta.textContent = match[2].replaceAll(", ", " · ");
    head.appendChild(meta);
  }
  return head;
}

// Shows a reply from Cerberus. The model writes Markdown, so marked turns it
// into HTML. Model text is never put in innerHTML without DOMPurify: it
// removes anything that could run, like <script> or onerror="...".
function showReply(el, label, text) {
  el.classList.remove("pending"); // the words are here: no more shimmer
  el.innerHTML = DOMPurify.sanitize(marked.parse(text));
  el.prepend(replyHead(label));
  el.classList.add("reply");
  renderDocumentSources(el, el.documentSources || []);
  if (currentProject && text.trim()) {
    const save = document.createElement("button");
    save.className = "save-document";
    save.textContent = "Save as document";
    save.addEventListener("click", () => openDocumentEditor(null, text));
    el.appendChild(save);
  }
  // highlight.js colors the code blocks.
  for (const block of el.querySelectorAll("pre code")) {
    hljs.highlightElement(block);
    addCopyButton(block);
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// Only numbers in the server's source list become clickable citations.
function renderDocumentSources(el, sources) {
  el.querySelector(".answer-sources")?.remove();
  if (!sources.length) return;
  const byNumber = new Map(sources.map(source => [String(source.number), source]));
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    if (!walker.currentNode.parentElement.closest("a, button, pre, code")) nodes.push(walker.currentNode);
  }
  for (const node of nodes) {
    const matches = [...node.textContent.matchAll(/\[(\d+)\]/g)].filter(match => byNumber.has(match[1]));
    if (!matches.length) continue;
    const fragment = document.createDocumentFragment();
    let offset = 0;
    for (const match of matches) {
      fragment.append(node.textContent.slice(offset, match.index));
      fragment.append(sourceButton(byNumber.get(match[1]), match[0]));
      offset = match.index + match[0].length;
    }
    fragment.append(node.textContent.slice(offset));
    node.replaceWith(fragment);
  }
  const list = document.createElement("div");
  list.className = "answer-sources";
  const label = document.createElement("p");
  label.className = "hint";
  // Show what Cerberus searched for: it may differ from your words, like
  // "Python 3.15 release date" for "and when was it released?".
  const searched = sources.find(source => source.kind === "web" && source.query);
  label.textContent = (searched ? "Searched the web for “" + searched.query + "”. " : "") +
    "Sources supplied to the model — click to inspect:";
  list.appendChild(label);
  for (const source of sources) {
    // 🌐 marks what came from the internet, so it stands apart from your own files.
    const icon = source.kind === "web" ? "🌐 " : "";
    list.appendChild(sourceButton(source, icon + "[" + source.number + "] " + source.name));
  }
  el.appendChild(list);
}

function sourceButton(source, label) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "document-citation";
  button.textContent = label;
  button.title = "View source text: " + source.name;
  button.addEventListener("click", () => openFilePreview(source.document_id, source));
  return button;
}

// Puts a Copy button on a code block. The <pre> goes into a wrapper box,
// so the button stays in the corner even when the code scrolls sideways.
function addCopyButton(code) {
  const pre = code.parentElement;
  const box = document.createElement("div");
  box.className = "code-box";
  pre.before(box);
  box.appendChild(pre); // appendChild moves the <pre> into the box

  const button = document.createElement("button");
  button.type = "button";
  button.className = "copy";
  button.textContent = "Copy";
  button.addEventListener("click", async () => {
    try {
      // The clipboard only works on https or localhost, so 127.0.0.1 is fine.
      await navigator.clipboard.writeText(code.textContent);
      button.textContent = "Copied!";
    } catch (error) {
      button.textContent = "Can't copy";
    }
    // After 1.5 seconds, show "Copy" again.
    setTimeout(() => (button.textContent = "Copy"), 1500);
  });
  box.appendChild(button);
}

// Shows the Regenerate button under the last answer, when there is one.
function showRegenerate() {
  const last = history[history.length - 1];
  if (last && last.role === "assistant" && lastUserEl) {
    messagesEl.appendChild(regenButton);
  }
}

function makeBox(className, text) {
  const div = document.createElement("div");
  div.className = className;
  div.textContent = text;
  return div;
}

// ---------- Models ----------

let modelListRequest = 0;

function setModelStatus(state, title, detail) {
  document.getElementById("chat-connection").dataset.state = state;
  document.getElementById("connection-title").textContent = title;
  document.getElementById("connection-detail").textContent = detail;
  document.getElementById("connection-retry").textContent = state === "error" ? "Retry" : "Refresh";
}

function updateSelectedModelStatus() {
  if (!modelSelect.value) {
    setModelStatus("idle", "Choose a model", "Select a chat model below, or open Setup to connect an engine.");
    return;
  }
  setModelStatus("ready", "Ready · " + currentEngine.name, modelSelect.value);
}

// Connection problems belong in the status bar, not the conversation.
async function loadModels() {
  const request = ++modelListRequest;
  modelSelect.disabled = true;
  setModelStatus("loading", "Connecting to your AI…", "Checking available models");
  try {
    const response = await fetch("/models");
    if (!response.ok) throw new Error(await responseError(response));
    const data = await response.json();
    if (request !== modelListRequest) return;
    modelSelect.innerHTML = "";
    modelSelect.appendChild(new Option("Choose a model…", ""));
    if (data.engine) showEngine(data.engine);
    thinkingModels = new Set(data.thinking || []);
    toolModels = new Set(data.tools || []);
    visionModels = new Set(data.vision || []);
    for (const name of data.models) modelSelect.appendChild(new Option(name, name));
    let saved = null;
    try { saved = localStorage.getItem("cerberus-model"); } catch (_) { /* storage may be unavailable */ }
    modelSelect.value = saved === "" || data.models.includes(saved) ? saved : (data.models[0] || "");
    updateModelFeatures();
    if (!data.models.length) {
      setModelStatus("empty", "No chat models yet", currentEngine.kind === "ollama"
        ? "Open Models to download your first model."
        : "Load a chat model in " + currentEngine.name + ", then press Refresh.");
    } else updateSelectedModelStatus();
  } catch (error) {
    if (request !== modelListRequest) return;
    modelSelect.innerHTML = "";
    modelSelect.appendChild(new Option("Connect an engine in Setup", ""));
    modelSelect.value = "";
    thinkingModels = new Set();
    toolModels = new Set();
    visionModels = new Set();
    updateModelFeatures();
    setModelStatus("error", "Your AI needs attention", error.message || "Could not connect. Try again or open Setup.");
  } finally {
    if (request === modelListRequest) modelSelect.disabled = false;
  }
}

document.getElementById("connection-retry").addEventListener("click", () => loadModels());
document.getElementById("connection-setup").addEventListener("click", () => openSetup());

// Which engine answers. Ollama is the normal case: no badge. Another
// engine gets its name next to the model list, and a cloud engine a ☁ and
// an honest line under the message box, because messages leave the computer.
let currentEngine = { kind: "ollama", name: "Ollama", cloud: false };

function showEngine(engine) {
  currentEngine = engine || currentEngine;
  const badge = document.getElementById("engine-badge");
  badge.hidden = currentEngine.kind === "ollama";
  badge.classList.toggle("cloud", currentEngine.cloud);
  // "Hugging Face (cloud)" -> "Hugging Face": the ☁ already says cloud.
  const name = currentEngine.name.replace(" (cloud)", "");
  badge.textContent = (currentEngine.cloud ? "☁ " : "") + name;
  badge.title = currentEngine.cloud
    ? "A cloud engine: your messages are sent to " + name + "."
    : "Answered by " + name + ", on this computer.";
  const hint = document.querySelector(".composer-hint");
  if (hint) {
    hint.textContent = currentEngine.cloud
      ? "Enter to send · Shift+Enter for a new line · ☁ Your messages are sent to " + name
      : "Enter to send · Shift+Enter for a new line · Everything stays on this computer unless Web or Research is on";
  }
}

// Show only the buttons the chosen model can use: Think for thinking
// models, the image button for vision models.
function updateModelFeatures() {
  thinkToggle.hidden = !thinkingModels.has(modelSelect.value);
  toolsToggle.hidden = !toolModels.has(modelSelect.value);
  imageButton.hidden = !canTakeImages();
  updateChatOptions();
}

// A chat model can take images when it can see them itself, or when the
// Eyes feature describes them for it.
function canTakeImages() {
  return visionModels.has(modelSelect.value) || eyesReady;
}

// Asks the server if Eyes is on. Called when the page opens and after
// the settings are saved.
async function loadEyes() {
  try {
    const response = await fetch("/settings");
    if (!response.ok) throw new Error("Settings unavailable");
    const values = await response.json();
    eyesReady = values.eyes_on === "yes" && values.eyes_model !== "";
  } catch (_) {
    eyesReady = false;
  }
  updateModelFeatures();
}

// ---------- Chat list ----------

let selectingChats = false;
let deletingChats = false;
let visibleChatIds = [];
const selectedChatIds = new Set();
let chatListRequest = 0;

function updateChatSelection() {
  document.getElementById("select-chats").textContent = selectingChats ? "Cancel" : "Select";
  document.getElementById("select-chats").disabled = deletingChats;
  document.getElementById("select-all-chats-label").hidden = !selectingChats;
  const all = document.getElementById("select-all-chats");
  all.checked = visibleChatIds.length > 0 && selectedChatIds.size === visibleChatIds.length;
  all.indeterminate = selectedChatIds.size > 0 && !all.checked;
  all.disabled = deletingChats || !visibleChatIds.length;
  const remove = document.getElementById("delete-selected-chats");
  remove.hidden = !selectingChats;
  remove.disabled = deletingChats || !selectedChatIds.size;
  remove.textContent = deletingChats ? "Deleting…" : "Delete selected (" + selectedChatIds.size + ")";
  for (const box of chatList.querySelectorAll(".chat-select")) {
    box.checked = selectedChatIds.has(Number(box.value));
    box.disabled = deletingChats;
  }
}

function toggleChatSelection(id) {
  if (deletingChats) return;
  if (selectedChatIds.has(id)) selectedChatIds.delete(id);
  else selectedChatIds.add(id);
  updateChatSelection();
}

document.getElementById("select-chats").addEventListener("click", () => {
  if (deletingChats) return;
  selectingChats = !selectingChats;
  selectedChatIds.clear();
  document.getElementById("chat-selection-status").textContent = "";
  loadChats();
});
document.getElementById("select-all-chats").addEventListener("change", event => {
  if (deletingChats) return;
  selectedChatIds.clear();
  if (event.target.checked) for (const id of visibleChatIds) selectedChatIds.add(id);
  updateChatSelection();
});
document.getElementById("delete-selected-chats").addEventListener("click", deleteSelectedChats);

async function deleteSelectedChats() {
  if (deletingChats || !selectedChatIds.size) return;
  const ids = [...selectedChatIds];
  const status = document.getElementById("chat-selection-status");
  if (ids.includes(currentChatId) && (controller || attachmentUploads)) {
    status.textContent = "Stop the answer or wait for the upload before deleting the current chat.";
    return;
  }
  if (!confirm("Delete " + ids.length + " selected chat(s) and their attachments? This cannot be undone.")) return;
  deletingChats = true;
  updateChatSelection();
  let removed = 0;
  const failed = [];
  try {
    for (const id of ids) {
      try {
        const response = await fetch("/chats/" + id, {method: "DELETE"});
        if (!response.ok) throw new Error(await responseError(response));
        selectedChatIds.delete(id);
        removed++;
        if (id === currentChatId) newChat();
      } catch (error) { failed.push(error.message); }
    }
    status.textContent = "Deleted " + removed + " chat(s)." + (failed.length ? " " + failed.length + " failed: " + [...new Set(failed)].join(" ") : "");
    if (!failed.length) selectingChats = false;
  } finally {
    deletingChats = false;
    updateChatSelection();
    await loadChats();
    await loadProjects();
  }
}

// Draws the chat list in the sidebar: the project's chats inside a
// project, the normal chats everywhere else. With text in the search
// box, only the chats that contain it.
async function loadChats() {
  const requestId = ++chatListRequest;
  // URLSearchParams builds "project_id=3&q=hello" and encodes special
  // characters (spaces, &, ...) so they can't break the URL.
  const params = new URLSearchParams();
  if (currentProject) params.set("project_id", currentProject.id);
  const query = chatSearch.value.trim();
  if (query) params.set("q", query);

  const response = await fetch("/chats?" + params);
  const data = await response.json();
  if (requestId !== chatListRequest) return;
  visibleChatIds = data.chats.map(chat => chat.id);
  for (const id of selectedChatIds) if (!visibleChatIds.includes(id)) selectedChatIds.delete(id);

  chatList.innerHTML = ""; // empty the list, then build it again
  updateChatSelection();

  if (query && data.chats.length === 0) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "No chats match.";
    chatList.appendChild(li);
    return;
  }

  // The chats come newest first. A heading goes in whenever the group
  // changes: Today, Yesterday, Previous 7 days...
  let group = null;
  for (const chat of data.chats) {
    const label = dateGroup(chat.created_at);
    if (label !== group) {
      group = label;
      const heading = document.createElement("li");
      heading.className = "group";
      heading.textContent = label;
      chatList.appendChild(heading);
    }

    const li = document.createElement("li");
    if (chat.id === currentChatId) {
      li.className = "active";
    }

    const title = document.createElement("span");
    title.className = "title";
    title.textContent = chat.title;

    const edit = document.createElement("button");
    edit.className = "edit";
    edit.textContent = "✎";
    edit.title = "Rename chat";

    const del = document.createElement("button");
    del.className = "delete";
    del.textContent = "x";
    del.title = "Delete chat";

    li.addEventListener("click", () => selectingChats ? toggleChatSelection(chat.id) : openChat(chat.id));
    edit.addEventListener("click", (event) => {
      event.stopPropagation(); // rename only, don't open the chat
      renameChat(chat, title);
    });
    del.addEventListener("click", (event) => {
      // The x is inside the li. Without this, the click would also
      // reach the li and open the chat we are deleting.
      event.stopPropagation();
      deleteChat(chat.id);
    });

    if (selectingChats) {
      const box = document.createElement("input");
      box.type = "checkbox";
      box.className = "chat-select";
      box.value = chat.id;
      box.checked = selectedChatIds.has(chat.id);
      box.disabled = deletingChats;
      box.setAttribute("aria-label", "Select " + chat.title);
      box.addEventListener("click", event => event.stopPropagation());
      box.addEventListener("change", () => toggleChatSelection(chat.id));
      li.appendChild(box);
    }
    li.appendChild(title);
    if (!selectingChats) {
      li.appendChild(edit);
      li.appendChild(del);
    }
    chatList.appendChild(li);
  }
}

// Which group a chat belongs to, from its date ("2026-10-17T12:00:00").
function dateGroup(createdAt) {
  // Both dates at midnight, so only the day counts, not the hour.
  const day = new Date(createdAt.slice(0, 10) + "T00:00:00");
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  // Subtracting dates gives milliseconds; 86400000 ms = one day.
  const daysAgo = Math.round((today - day) / 86400000);

  if (daysAgo <= 0) return "Today";
  if (daysAgo === 1) return "Yesterday";
  if (daysAgo < 7) return "Previous 7 days";
  if (daysAgo < 30) return "Previous 30 days";
  return "Older";
}

// Swaps the chat's title for a text box. Enter (or clicking elsewhere)
// saves, Escape cancels. Either way the list is drawn again at the end.
function renameChat(chat, titleEl) {
  const field = document.createElement("input");
  field.className = "rename";
  field.value = chat.title;
  titleEl.replaceWith(field);
  field.focus();
  field.select(); // select all, so typing replaces the old title

  let done = false;
  async function finish(save) {
    // Enter and then losing focus would both call finish, so only
    // the first call counts.
    if (done) return;
    done = true;

    const title = field.value.trim();
    if (save && title && title !== chat.title) {
      await fetch("/chats/" + chat.id, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title }),
      });
    }
    loadChats();
  }

  field.addEventListener("keydown", (event) => {
    if (event.key === "Enter") finish(true);
    if (event.key === "Escape") finish(false);
  });
  // "blur" = the box lost focus, because the user clicked somewhere else.
  field.addEventListener("blur", () => finish(true));
  // A click inside the box would bubble up to the li and open the chat.
  field.addEventListener("click", (event) => event.stopPropagation());
}

// Loads a saved chat from the server and shows all its messages.
async function openChat(id) {
  // Returning to the chat panel must work even while an answer/upload is running.
  showFeature("chat");
  if (controller || (typeof attachmentUploads !== "undefined" && attachmentUploads)) {
    if (id !== currentChatId) attachStatus.textContent = "Stop the current answer or wait for the upload before switching chats.";
    return;
  }
  if (id !== currentChatId) recapChat(currentChatId); // NEW (projects step 2)

  let response;
  try {
    response = await fetch("/chats/" + id);
  } catch (_) {
    attachStatus.textContent = "Could not open the chat. Check that Cerberus is running and try again.";
    return;
  }
  if (!response.ok) {
    attachStatus.textContent = await responseError(response);
    return;
  }
  const chat = await response.json();

  currentChatId = chat.id;
  history = chat.messages;

  messagesEl.innerHTML = "";
  attachChips.innerHTML = ""; // NEW
  if (chat.documents?.length) {
    const files = addMessage("");
    for (const doc of chat.documents) {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.appendChild(filePreviewButton(doc));
      files.appendChild(chip);
    }
  }
  lastUserEl = null;
  for (const [index, message] of history.entries()) {
    if (message.role === "user") {
      lastUserEl = addUserMessage(message.content);
      addImagesTo(lastUserEl, message.images);
      if (message.seen) showSeen(lastUserEl, message.seen);
    } else {
      const bubble = addMessage("");
      bubble.documentSources = chat.sources?.[String(index)] || [];
      showReply(bubble, "Cerberus:", message.content);
    }
  }
  showRegenerate();

  loadChats(); // redraw the list, so the open chat is highlighted
  showFeature("chat");
}

// An empty chat. It's only saved on the server when the first message is sent.
function newChat() {
  showFeature("chat");
  if (controller || (typeof attachmentUploads !== "undefined" && attachmentUploads)) return;
  recapChat(currentChatId); // NEW (projects step 2)
  currentChatId = null;
  history = [];
  lastUserEl = null;
  messagesEl.innerHTML = "";
  attachStatus.textContent = "";
  attachChips.innerHTML = ""; // NEW: chips go, the documents stay in Memory
  pendingImages = [];
  showPendingImages();
  showHome();
  loadChats();
  showFeature("chat");
  input.focus();
}

// ---------- Home screen ----------

// Example questions. A click puts one in the message box (it doesn't send
// it), so you can change it first.
const SUGGESTIONS = [
  "Explain how a hash table works",
  "Help me find the bug in this code:",
  "Help me plan my week",
  "Help me write a clear, friendly email",
];

// The big "Cerberus" in the middle of an empty chat.
function showHome() {
  const home = document.createElement("div");
  home.id = "home";

  // The logo above the name. A fixed piece of HTML, so innerHTML is safe.
  const logo = document.createElement("div");
  logo.className = "home-logo";
  logo.innerHTML = '<svg class="logo"><use href="#i-logo"/></svg>';

  const title = document.createElement("h1");
  title.textContent = "What would you like to work on?"

  const tagline = document.createElement("p");
  tagline.className = "tagline";
  tagline.textContent = currentProject
    ? "Project: " + currentProject.name
    : "Ask a question, write something, or work through an idea.";

  const suggestions = document.createElement("div");
  suggestions.className = "suggestions";
  for (const text of SUGGESTIONS) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    button.addEventListener("click", () => {
      input.value = text;
      resizeInput();
      input.focus();
    });
    suggestions.appendChild(button);
  }

  home.append(logo, title, tagline, suggestions);
  messagesEl.appendChild(home);
}

// Clicking the name in the sidebar: a new, empty chat with the home screen.
document.getElementById("home-button").addEventListener("click", newChat);

async function deleteChat(id) {
  if ((controller || attachmentUploads) && id === currentChatId) return;
  if (!confirm("Delete this chat?")) return;

  const response = await fetch("/chats/" + id, { method: "DELETE" });
  if (!response.ok) { alert(await responseError(response)); return; }

  if (id === currentChatId) {
    newChat(); // we deleted the open chat, so start a fresh one
  } else {
    loadChats();
  }
}

// Creates the chat on the server the first time it's needed.
async function ensureChat() {
  if (currentChatId) return;

  const response = await fetch("/chats", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: currentProject ? currentProject.id : null }),
  });
  if (!response.ok) throw new Error(await responseError(response));
  const chat = await response.json();
  currentChatId = chat.id;
}

// Asks the server to give this chat a short title.
async function makeTitle(model) {
  try {
    await fetch("/chats/" + currentChatId + "/title", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: model }),
    });
  } catch (error) {
    // A missing title isn't worth an error message.
  }
}

// NEW (projects step 2): when you leave a chat inside a project, the server
// writes a short recap of it into the project's notes. We don't wait for it.
function recapChat(chatId) {
  // The server checks project membership. The UI may already have left it.
  if (!chatId || !modelSelect.value) return;

  fetch("/chats/" + chatId + "/recap", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: modelSelect.value }),
    keepalive: true, // still sent when the page is closing
  }).catch(() => {
    // A missing recap isn't worth an error message.
  });
}

// ---------- Sending ----------

// A normal answer. Returns the reply text, or null when there is no reply
// (an error, or stopped before the first word).
// url: "/chat" for a normal answer, "/research" for the research agent.
// Both stream the same kind of events, so one function reads both.
async function sendNormal(model, url = "/chat") {
  const researching = url === "/research";
  // When the Eyes have to look at an image first, say so: it takes a while.
  const last = history[history.length - 1];
  const looking = last.images && last.images.length > 0 && !last.seen && !visionModels.has(model);
  const bubble = addMessage(
    researching ? "Cerberus is starting the research..." :
    looking ? "Cerberus is looking at the image..." : "Cerberus is thinking..."
  );
  // It shimmers while Cerberus works (.pending in style.css). showReply
  // and send() take the shimmer away again.
  bubble.classList.add("pending");

  let response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: history,
        model: model,
        chat_id: currentChatId,
        think: wantsThinking(),
        tools: wantsTools(),
        web: webCheck.checked,
      }),
      // The signal connects this request to the Stop button.
      signal: controller.signal,
    });
  } catch (error) {
    // AbortError = the user pressed Stop. Any other error goes up to the caller.
    if (error.name !== "AbortError") throw error;
    bubble.textContent = "Cerberus: (stopped)";
    return null;
  }

  if (!response.ok) {
    bubble.textContent = "Cerberus: " + await responseError(response);
    return null;
  }

  const who = researching ? "Cerberus (Research):" : "Cerberus (" + replyLabel(response.headers) + "):";
  bubble.textContent = researching ? "Cerberus is researching..." : who + " ...";
  showWebError(response.headers, bubble);

  const result = await readReply(response, bubble, who, (ev) => {
    if (ev.type === "progress") {
      showProgress(bubble, ev);
    } else if (ev.type === "seen") {
      // What the Eyes saw: keep it with the question, so they never
      // have to look at this picture again, and show it.
      history[history.length - 1].seen = ev.text;
      showSeen(lastUserEl, ev.text, ev.model);
    }
  }, true);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  // The server saves a stopped answer too, so we keep it here as well.
  return finishReply(result, bubble, who);
}

// The research agent's steps, in a box above its report. Each new step
// marks the one before as done (✓). The last step names the saved
// document, with a button that opens it in the editor.
function showProgress(bubble, ev) {
  if (!bubble.progressBox) {
    const details = document.createElement("details");
    details.className = "research-steps";
    details.open = true;
    const summary = document.createElement("summary");
    summary.textContent = "Research steps";
    details.append(summary, document.createElement("ol"));
    bubble.before(details);
    bubble.progressBox = details;
  }
  const list = bubble.progressBox.querySelector("ol");
  list.lastElementChild?.classList.add("done");
  const step = document.createElement("li");
  step.textContent = ev.text; // textContent: a page title can never become code
  if (ev.document_id) {
    step.classList.add("done");
    const open = document.createElement("button");
    open.type = "button";
    open.className = "mini";
    open.textContent = "Open report";
    open.addEventListener("click", () => openDocumentEditor(ev.document_id));
    step.append(" ", open);
  }
  list.appendChild(step);
}

// Reads a streamed answer (NDJSON like /chat sends it) into bubble: the
// thinking, the answer, the stats and errors. Event types it doesn't know
// (like "seen") go to onOther. The main chat and the Reverse panel both
// use it. Returns { reply, stats, failure, stopped }.
async function readReply(response, bubble, who, onOther, requireDone = false) {
  const result = { reply: "", stats: null, failure: null, stopped: false, done: false };
  let thinkBox = null; // the fold-out box, made when the first thought arrives

  try {
    await readEvents(response, (ev) => {
      if (ev.type === "done") {
        result.done = true;
        result.stopped = ev.stopped;
        if (ev.error) result.failure = ev.error;
        if (ev.saved === false && result.reply) result.failure = ev.error || "This answer was not saved.";
      } else if (ev.type === "sources") {
        bubble.documentSources = ev.sources;
      } else if (ev.type === "thinking") {
        thinkBox = thinkBox || makeThinkingBox(bubble);
        thinkBox.lastChild.textContent += ev.text;
      } else if (ev.type === "content") {
        // The first word of the answer: thinking is over.
        if (thinkBox && !result.reply) {
          thinkBox.firstChild.textContent = "Show thinking";
        }
        result.reply += ev.text;
        showReply(bubble, who, result.reply);
        bubble.classList.add("streaming"); // the mascot nods while the words arrive
      } else if (ev.type === "stats") {
        result.stats = ev;
      } else if (ev.type === "tool") {
        showToolCall(bubble, ev);
        bubble.textContent = who + " ..."; // the model goes on after the tool
      } else if (ev.type === "error") {
        result.failure = ev.text;
      } else if (onOther) {
        onOther(ev);
      }
    });
  } catch (error) {
    // AbortError = the user pressed Stop: keep whatever arrived.
    // Any other error goes up to the caller.
    if (error.name !== "AbortError") throw error;
    result.stopped = true;
  } finally {
    bubble.classList.remove("streaming");
  }
  if (requireDone && !result.done && !result.stopped && !result.failure) {
    result.failure = "The connection ended before saving was confirmed. Reopen the chat to check its saved messages.";
  }
  return result;
}

// Shows how an answer ended, and returns its text (null = no answer).
function finishReply(result, bubble, who) {
  if (result.failure) {
    if (result.reply) showReply(bubble, who, result.reply);
    else bubble.textContent = "Cerberus: no answer.";
    bubble.after(makeBox("hint", result.failure));
    return null;
  }
  if (result.stopped) {
    if (!result.reply) {
      bubble.textContent = "Cerberus: (stopped before an answer)";
      return null;
    }
    showReply(bubble, who, result.reply);
    bubble.after(makeBox("hint", result.done ? "Stopped. Partial answer saved." : "Stopped."));
    return result.reply;
  }
  if (!result.reply) {
    // This happens when a thinking model uses up all its tokens on thinking.
    bubble.textContent = "Cerberus: (no answer, the model ran out of tokens while thinking)";
    return null;
  }
  if (result.stats) showStats(bubble, result.stats);
  return result.reply;
}

// Reads an NDJSON stream (one JSON object per line) and calls onEvent with
// each object as soon as its line is complete. Normal chat and Deep think
// both use it.
async function readEvents(response, onEvent) {
  // The answer arrives in pieces of bytes; the decoder turns them into text.
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      buffer += decoder.decode();
      if (buffer.trim()) onEvent(JSON.parse(buffer));
      break;
    }
    // stream: true = a letter split over two pieces (like "é") isn't broken.
    buffer += decoder.decode(value, { stream: true });

    // A piece can end in the middle of a line, so the last, unfinished
    // line stays in the buffer until the rest of it arrives.
    const lines = buffer.split("\n");
    buffer = lines.pop();

    for (const line of lines) {
      if (line.trim()) onEvent(JSON.parse(line));
    }
  }
}

// The fold-out box with the model's thinking, placed above the answer.
// It starts closed: you only see "Thinking...", so you know the model is
// working, and you can click it if you want to read the thoughts.
function makeThinkingBox(bubble) {
  const details = document.createElement("details");
  details.className = "thinking";
  const summary = document.createElement("summary");
  summary.textContent = "Thinking...";
  const body = document.createElement("div");
  details.append(summary, body);
  bubble.before(details);
  return details;
}

// A small line under the answer, like:
// "312 tokens · 24.1 tok/s · context 1,532 / 8,192"
function showStats(bubble, stats) {
  // toFixed(1) = one decimal; toLocaleString() adds thousands separators.
  const speed = stats.seconds ? (stats.tokens / stats.seconds).toFixed(1) : "?";
  const parts = [
    stats.tokens + " tokens",
    speed + " tok/s",
    "context " + stats.context.toLocaleString() + " / " + stats.num_ctx.toLocaleString(),
  ];
  if (stats.cut_off) parts.push("cut off at the token limit");

  const line = document.createElement("div");
  line.className = "stats";
  line.textContent = parts.join(" · ");
  bubble.after(line);
}

// True when the user wants thinking and the chosen model can do it.
function wantsThinking() {
  return thinkCheck.checked && !thinkToggle.hidden;
}

// True when the user wants tools and the chosen model can use them.
function wantsTools() {
  return toolsCheck.checked && !toolsToggle.hidden;
}

// One folded line for each tool the model used, above the answer:
// "🔧 calculate(1234*5678) → 7006652". Click it to see the full result.
// You always see what was run, with what, and what came back.
function showToolCall(bubble, ev) {
  const details = document.createElement("details");
  details.className = "tool-call";

  // Object.values({ expression: "6*7" }) gives ["6*7"].
  const inputs = Object.values(ev.arguments).join(", ");
  const short = ev.result.replace(/\s+/g, " "); // one line: no line breaks
  const summary = document.createElement("summary");
  summary.textContent =
    "🔧 " + ev.name + "(" + inputs + ") → " + (short.length > 70 ? short.slice(0, 70) + "..." : short);

  const result = document.createElement("pre");
  result.textContent = ev.result;

  details.append(summary, result);
  bubble.before(details);
}

// A Deep think answer: the draft and the review go in a fold-out box,
// the final answer is shown on top. Returns the final text, or null.
async function sendCouncil(model) {
  const container = document.createElement("div");
  const answer = makeBox("judge", "Cerberus is thinking deeply...");
  answer.classList.add("pending"); // shimmers while it works, like a normal answer

  // <details> is a box the user can open and close; <summary> is its title.
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = "Show how Cerberus thought";
  details.appendChild(summary);

  const stepsRow = makeBox("heads", "");
  const boxes = {};
  for (const name of ["draft", "review"]) {
    boxes[name] = makeBox("head", STEP_LABELS[name] + ": waiting...");
    stepsRow.appendChild(boxes[name]);
  }
  details.appendChild(stepsRow);

  container.appendChild(answer);
  container.appendChild(details);
  messagesEl.appendChild(container);

  const texts = { draft: "", review: "", final: "" };
  let failed = false;
  let completed = false;

  try {
    const response = await fetch("/council", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: history,
        model: model,
        chat_id: currentChatId,
        web: webCheck.checked,
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      answer.textContent = "Cerberus: " + await responseError(response);
      return null;
    }

    const label = replyLabel(response.headers);
    showWebError(response.headers, answer);

    await readEvents(response, (ev) => {
      if (ev.step === "sources") {
        answer.documentSources = ev.sources;
        return;
      }
      if (ev.step === "done") {
        completed = true;
        if (ev.stopped) answer.after(makeBox("hint", texts.final ? "Stopped. Partial answer saved." : "Stopped before the final answer."));
        if (ev.error) { answer.after(makeBox("hint", ev.error)); failed = true; }
        if (!texts.final) answer.textContent = "Cerberus: no final answer.";
        return;
      }
      if (ev.step === "seen") {
        history[history.length - 1].seen = ev.text;
        showSeen(lastUserEl, ev.text);
        return;
      }
      if (ev.step === "error") {
        answer.textContent = "Cerberus: " + ev.text;
        failed = true;
        return;
      }

      texts[ev.step] += ev.text;

      if (ev.step === "final") {
        showReply(answer, "Cerberus (Deep think, " + label + "):", texts.final);
      } else {
        boxes[ev.step].textContent = STEP_LABELS[ev.step] + ": " + texts[ev.step];
        answer.textContent = "Cerberus is writing its " + STEP_LABELS[ev.step].toLowerCase() + "...";
      }
      messagesEl.scrollTop = messagesEl.scrollHeight;
    });
  } catch (error) {
    if (error.name !== "AbortError") throw error;
    answer.textContent = "Cerberus: (stopped)";
    return null;
  }

  if (!completed) answer.after(makeBox("hint", "Saving was not confirmed. Reopen the chat to check."));
  return failed || !completed || !texts.final ? null : texts.final;
}

// Sends one question and shows the answer. The form uses it, and so does
// Regenerate, which is why it's a function of its own.
async function responseError(response) {
  try {
    const data = await response.json();
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) return data.detail.map((item) => item.msg).join("; ");
  } catch (_) { /* A proxy may return a non-JSON error. */ }
  return "The server answered with error " + response.status + ".";
}

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let stoppingAnswer = false;

async function stopAnswer() {
  if (!controller || stoppingAnswer) return;
  const running = controller;
  stoppingAnswer = true;
  sendButton.textContent = "Stopping...";
  try {
    // A very quick click can arrive while the new chat is still being created,
    // or before /chat reaches the server. Retry until that run is registered.
    while (controller === running) {
      if (currentChatId) {
        const response = await fetch("/chats/" + currentChatId + "/stop", { method: "POST" });
        if (!response.ok) throw new Error(await responseError(response));
        if ((await response.json()).stopping) break;
      }
      await pause(200);
    }
  } catch (error) {
    attachStatus.textContent = "Could not stop the answer: " + error.message;
    if (controller === running) sendButton.textContent = "Stop";
  } finally {
    stoppingAnswer = false;
  }
}

async function committedChat() {
  for (let attempt = 0; attempt < 30; attempt++) {
    const response = await fetch("/chats/" + currentChatId);
    if (!response.ok) throw new Error(await responseError(response));
    const chat = await response.json();
    if (!chat.answering) return chat;
    await pause(100);
  }
  throw new Error("The server is still answering. Press Stop or reopen this chat shortly.");
}

async function send(text, model, images = [], seen = "") {
  if (controller || (typeof attachmentUploads !== "undefined" && attachmentUploads)) return;
  controller = new AbortController(); // also prevents navigation and double submits
  sendButton.textContent = "Stop";
  let sent = false;
  const previousUserEl = lastUserEl;
  const previousCount = history.length;
  try {
    await ensureChat();
    regenButton.remove();
    document.getElementById("home")?.remove();
    lastUserEl = addUserMessage(text);
    addImagesTo(lastUserEl, images);
    // Sent attachments belong in the conversation, leaving the composer clear.
    for (const chip of [...attachChips.children]) {
      chip.querySelector(".chip-x")?.remove();
      lastUserEl.appendChild(chip);
    }
    attachStatus.textContent = "";
    history.push({ role: "user", content: text, images, seen });
    sent = true;
    const reply = researchCheck.checked ? await sendNormal(model, "/research")
      : threeHeads.checked ? await sendCouncil(model) : await sendNormal(model);
    // Read the committed history, including partial answers, rather than guessing
    // what the server saved after Stop or an upstream error.
    history = (await committedChat()).messages;
    if (history.length <= previousCount) lastUserEl = previousUserEl;
    showRegenerate();
    if (reply && history.length === 2) makeTitle(model).then(loadChats);
  } catch (error) {
    if (sent) {
      try {
        history = (await committedChat()).messages;
        if (history.length <= previousCount) lastUserEl = previousUserEl;
      } catch (_) { /* A stale history is rejected by the server on the next send. */ }
    }
    addMessage("Cerberus: " + error.message + " Reopen the chat to check saved messages.");
  } finally {
    controller = null;
    sendButton.textContent = "Send";
    // However it ended (answer, Stop, error): nothing shimmers anymore.
    for (const el of messagesEl.querySelectorAll(".pending")) el.classList.remove("pending");
    loadChats();
  }
}

// Regenerate: forget the last answer and ask the same question again.
// The model picks its words with some randomness, so the new answer differs.
async function regenerate() {
  const model = modelSelect.value;
  if (controller || !lastUserEl || !model) return;

  // The last two entries in history are the question and its answer.
  // { content, images } = ... takes those two fields out of the object.
  const { content, images, seen } = history[history.length - 2];
  const removed = await fetch("/chats/" + currentChatId + "/last-turn", { method: "DELETE" });
  if (!removed.ok) { attachStatus.textContent = await responseError(removed); return; }
  history.splice(-2); // remove both from the page's history too

  // Remove the question and everything after it from the screen.
  while (lastUserEl.nextSibling) lastUserEl.nextSibling.remove();
  lastUserEl.remove();

  // seen goes along too, so the Eyes don't have to look again.
  await send(content, model, images || [], seen || "");
}

form.addEventListener("submit", async (event) => {
  // A form normally reloads the page when submitted. We handle it ourselves.
  event.preventDefault();

  // One button, two jobs. If an answer is running, a click means Stop.
  if (controller) {
    await stopAnswer();
    return;
  }

  if (attachmentUploads) { attachStatus.textContent = "Please wait for the file upload to finish."; return; }
  const text = input.value.trim();
  if (!text && pendingImages.length === 0) return;

  const model = modelSelect.value;
  if (!model) {
    attachStatus.textContent = "Choose a chat model below, or open Setup to connect your AI.";
    modelSelect.focus();
    return;
  }

  input.value = "";
  resizeInput(); // shrink the box back to one line
  const images = pendingImages;
  pendingImages = [];
  showPendingImages();
  // An image alone, without a question, gets a default question.
  await send(text || "What is in this image?", model, images);
});

// ---------- The message box ----------

// The box grows with its text: reset the height, then set it to the
// height the text really needs (scrollHeight). CSS caps it at max-height.
function resizeInput() {
  input.style.height = "auto";
  input.style.height = input.scrollHeight + "px";
}

input.addEventListener("input", resizeInput);

input.addEventListener("keydown", (event) => {
  // Enter sends, Shift+Enter makes a new line. isComposing is true while
  // typing with an input method (for example Japanese), where Enter picks
  // a word instead of sending.
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault(); // don't add a new line
    // requestSubmit() submits the form, just like a click on Send.
    // Not while an answer runs: Enter shouldn't press Stop by accident.
    if (!controller) form.requestSubmit();
  }
});

newChatButton.addEventListener("click", newChat);

// ---------- Search ----------

// Debouncing: searching on every key press would send "p", "py", "pyt"...
// Instead each key press restarts a 250 ms timer, and we only search when
// the user stops typing for a moment.
let searchTimer = null;
chatSearch.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadChats, 250);
});

// Escape empties the search box and shows all chats again.
chatSearch.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    chatSearch.value = "";
    loadChats();
  }
});

// Free the RAM of the models we don't use anymore. Ollama keeps every
// model it used in memory for 30 minutes; we tell it to let go of the old
// ones right away. We don't wait for it, the chat works meanwhile.
// With None chosen (value ""), every model is unloaded.
function freeOtherModels() {
  fetch("/models/keep", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: modelSelect.value }),
  })
    .then((response) => response.json())
    .then((data) => {
      if (data.unloaded.length > 0) {
        attachStatus.textContent = "Freed memory: " + data.unloaded.join(", ");
      } else if (!modelSelect.value) {
        attachStatus.textContent = "No model is loaded.";
      }
    })
    .catch(() => {
      // Not freeing memory isn't worth an error message.
    });
}

modelSelect.addEventListener("change", freeOtherModels);

// Remember the chosen model for the next visit.
modelSelect.addEventListener("change", () => {
  try { localStorage.setItem("cerberus-model", modelSelect.value); } catch (_) { /* storage may be unavailable */ }
  updateModelFeatures();
  updateSelectedModelStatus();
});

// Research and Deep think can't both run: ticking one unticks the other.
researchCheck.addEventListener("change", () => { if (researchCheck.checked) threeHeads.checked = false; });
threeHeads.addEventListener("change", () => { if (threeHeads.checked) researchCheck.checked = false; });

// Remember the Web box too. The very first time it's off: searching
// sends your question to the internet, so that must be your choice.
webCheck.checked = localStorage.getItem("cerberus-web") === "yes";
webCheck.addEventListener("change", () => {
  localStorage.setItem("cerberus-web", webCheck.checked ? "yes" : "no");
});

// NEW (projects step 2): closing or reloading the page also leaves the chat.
window.addEventListener("pagehide", () => recapChat(currentChatId));

// ---------- + button (documents) ----------

// documents.js owns the file picker and the upload. It also declares
// documentFile and documentStatus, and all scripts on a page share one
// space, so here we look the elements up by id instead of declaring them again.
attachButton.addEventListener("click", () => {
  if (!controller && !attachmentUploads) document.getElementById("chat-document-file").click();
});

let attachmentUploads = false;
document.getElementById("chat-document-file").addEventListener("change", async event => {
  if (controller || attachmentUploads) return;
  attachmentUploads = true;
  try {
    await ensureChat();
    const chatId = currentChatId;
    for (const file of event.target.files) await uploadFile(file, chatId);
    await loadChats();
  } catch (error) { attachStatus.textContent = error.message; }
  finally { attachmentUploads = false; event.target.value = ""; }
});

// Copy the upload messages from the Documents tab to just above the message box.
// A MutationObserver calls our function whenever the watched element changes.
new MutationObserver(() => {
  attachStatus.textContent = document.getElementById("document-status").textContent;
}).observe(document.getElementById("document-status"), {
  childList: true,
  characterData: true,
  subtree: true,
});

// NEW: one chip per uploaded file, with an x that removes it from Cerberus.
function addChip(doc) {
  const chip = document.createElement("span");
  chip.className = "chip";

  const name = filePreviewButton(doc);

  const remove = document.createElement("button");
  remove.type = "button"; // inside a form, a plain button would submit it
  remove.className = "chip-x";
  remove.textContent = "×";
  remove.title = "Remove this attachment from the chat";
  remove.addEventListener("click", async () => {
    if (controller || (typeof attachmentUploads !== "undefined" && attachmentUploads)) return;
    const response = await fetch("/documents/" + doc.id, { method: "DELETE" });
    if (!response.ok) { attachStatus.textContent = await responseError(response); return; }
    chip.remove();
    attachStatus.textContent = "";
  });

  chip.append(name, remove);
  attachChips.appendChild(chip);
}

function filePreviewButton(doc) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "file-preview-link";
  button.textContent = "📄 " + doc.name;
  button.title = "Preview " + doc.name;
  button.addEventListener("click", () => openFilePreview(doc.id));
  return button;
}

// NEW: documents.js announces each finished upload. Show a chip only when
// the upload came from the chat, not from the Memory panel.
document.addEventListener("document-added", (event) => {
  if (event.detail.chat_id === currentChatId) {
    addChip(event.detail);
  }
});

// ---------- Images ----------

const MAX_IMAGES = 4; // per message
const IMAGE_SIZE = 1024; // the longest side, in pixels, after shrinking

// Shrinks a picture and turns it into base64 text, the format Ollama wants.
// A 4000-pixel photo would be slow for a model on a CPU, and it doesn't
// need that much detail, so the longest side becomes at most IMAGE_SIZE.
function readImage(file) {
  // A Promise is a value that arrives later. We make one by hand, because
  // an <img> tells us it finished loading with an event, not with await.
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, IMAGE_SIZE / Math.max(img.width, img.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);

      const draw = canvas.getContext("2d");
      // JPEG has no transparency, so paint white first (instead of black).
      draw.fillStyle = "#fff";
      draw.fillRect(0, 0, canvas.width, canvas.height);
      draw.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(img.src); // free the memory of the original file

      // toDataURL gives "data:image/jpeg;base64,AAAA...". Ollama wants only
      // the part after the comma.
      resolve(canvas.toDataURL("image/jpeg", 0.85).split(",")[1]);
    };
    img.onerror = () => reject(new Error("not an image"));
    // An object URL lets an <img> show a file from the user's computer.
    img.src = URL.createObjectURL(file);
  });
}

// Adds picked or pasted files to the images waiting to be sent.
async function addImages(files) {
  if (!canTakeImages()) {
    attachStatus.textContent =
      "This model can't see images. Pick a vision model (like gemma3:4b), or turn on Eyes in Settings.";
    return;
  }
  for (const file of files) {
    if (!file.type.startsWith("image/")) continue;
    if (pendingImages.length >= MAX_IMAGES) {
      attachStatus.textContent = "Up to " + MAX_IMAGES + " images per message.";
      break;
    }
    try {
      pendingImages.push(await readImage(file));
    } catch (error) {
      attachStatus.textContent = file.name + " could not be read.";
    }
  }
  showPendingImages();
}

// Draws the waiting images as small pictures, each with an x to remove it.
function showPendingImages() {
  imageChips.innerHTML = "";
  // forEach gives each item and its position (index) in the list.
  pendingImages.forEach((base64, index) => {
    const chip = document.createElement("span");
    chip.className = "image-chip";

    const img = document.createElement("img");
    img.src = "data:image/jpeg;base64," + base64;

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "chip-x";
    remove.textContent = "×";
    remove.title = "Remove this image";
    remove.addEventListener("click", () => {
      pendingImages.splice(index, 1); // remove 1 item at this position
      showPendingImages();
    });

    chip.append(img, remove);
    imageChips.appendChild(chip);
  });
}

// Under a user's images: what the Eyes saw in them, folded away.
function showSeen(el, text, model) {
  const details = document.createElement("details");
  details.className = "seen";
  const summary = document.createElement("summary");
  summary.textContent = "What " + (model || "the Eyes") + " saw";
  const body = document.createElement("div");
  body.textContent = text;
  details.append(summary, body);
  el.appendChild(details);
}

// Shows a message's images under its text.
function addImagesTo(el, images) {
  if (!images || images.length === 0) return;
  const row = document.createElement("div");
  row.className = "message-images";
  for (const base64 of images) {
    const img = document.createElement("img");
    img.src = "data:image/jpeg;base64," + base64;
    row.appendChild(img);
  }
  el.appendChild(row);
}

imageButton.addEventListener("click", () => imageFile.click());

imageFile.addEventListener("change", async () => {
  await addImages(imageFile.files);
  imageFile.value = ""; // so picking the same file again works
});

// Paste a screenshot straight into the message box with Ctrl+V.
input.addEventListener("paste", (event) => {
  // [...list] turns the clipboard's file list into a normal array.
  const files = [...event.clipboardData.files].filter((file) => file.type.startsWith("image/"));
  if (files.length > 0) {
    event.preventDefault(); // don't paste the file name as text
    addImages(files);
  }
});

// Keep active options visible even when their controls are tucked away.
function updateChatOptions() {
  const options = [];
  if (researchCheck.checked) options.push("Research");
  else if (threeHeads.checked) options.push("Deep think");
  if (webCheck.checked) options.push("Web");
  if (!thinkToggle.hidden && thinkCheck.checked) options.push("Think");
  if (!toolsToggle.hidden && toolsCheck.checked) options.push("Tools");
  document.getElementById("chat-options-summary").textContent = options.length ? options.join(" · ") : "Standard";
}
for (const checkbox of [researchCheck, threeHeads, webCheck, thinkCheck, toolsCheck]) {
  checkbox.addEventListener("change", updateChatOptions);
}
const chatOptions = document.getElementById("chat-options");
document.addEventListener("click", event => {
  if (chatOptions.open && !chatOptions.contains(event.target)) chatOptions.open = false;
});
chatOptions.addEventListener("keydown", event => {
  if (event.key === "Escape" && chatOptions.open) {
    chatOptions.open = false;
    chatOptions.querySelector("summary").focus();
    event.preventDefault();
    event.stopPropagation();
  }
});
updateChatOptions();

// ---------- Start ----------

// When the page opens, only the chosen model stays in memory too.
loadModels().then(loadEyes).then(freeOtherModels);
loadChats();
showHome(); // no chat is open yet
