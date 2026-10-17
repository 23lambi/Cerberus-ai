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
const thinkToggle = document.getElementById("think-toggle");
const thinkCheck = document.getElementById("think");
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
  return [mode, ...sourceLabels(headers)].join(", ");
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

// Shows a reply from Cerberus. The model writes Markdown, so marked turns it
// into HTML. Model text is never put in innerHTML without DOMPurify: it
// removes anything that could run, like <script> or onerror="...".
function showReply(el, label, text) {
  const who = document.createElement("strong");
  who.textContent = label;
  el.innerHTML = DOMPurify.sanitize(marked.parse(text));
  el.prepend(who);
  el.classList.add("reply");
  // highlight.js colors the code blocks.
  for (const block of el.querySelectorAll("pre code")) {
    hljs.highlightElement(block);
    addCopyButton(block);
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
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

// Fills the model dropdown with the models installed in Ollama.
async function loadModels() {
  const response = await fetch("/models");
  const data = await response.json();

  // response.ok is false for errors like 503 (Ollama isn't running).
  if (!response.ok) {
    addMessage("Cerberus: " + data.detail);
    return;
  }

  if (data.models.length === 0) {
    addMessage("No models found. Install one with: ollama pull llama3.2");
    return;
  }

  for (const name of data.models) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    modelSelect.appendChild(option);
  }

  // Pick the model used last time, if it's still installed.
  const saved = localStorage.getItem("cerberus-model");
  if (saved && data.models.includes(saved)) {
    modelSelect.value = saved;
  }

  // A Set is a list where each value appears once, with a fast .has().
  thinkingModels = new Set(data.thinking);
  visionModels = new Set(data.vision);
  updateModelFeatures();
}

// Show only the buttons the chosen model can use: Think for thinking
// models, the image button for vision models.
function updateModelFeatures() {
  thinkToggle.hidden = !thinkingModels.has(modelSelect.value);
  imageButton.hidden = !canTakeImages();
}

// A chat model can take images when it can see them itself, or when the
// Eyes feature describes them for it.
function canTakeImages() {
  return visionModels.has(modelSelect.value) || eyesReady;
}

// Asks the server if Eyes is on. Called when the page opens and after
// the settings are saved.
async function loadEyes() {
  const response = await fetch("/settings");
  const values = await response.json();
  eyesReady = values.eyes_on === "yes" && values.eyes_model !== "";
  updateModelFeatures();
}

// ---------- Chat list ----------

// Draws the chat list in the sidebar: the project's chats inside a
// project, the normal chats everywhere else. With text in the search
// box, only the chats that contain it.
async function loadChats() {
  // URLSearchParams builds "project_id=3&q=hello" and encodes special
  // characters (spaces, &, ...) so they can't break the URL.
  const params = new URLSearchParams();
  if (currentProject) params.set("project_id", currentProject.id);
  const query = chatSearch.value.trim();
  if (query) params.set("q", query);

  const response = await fetch("/chats?" + params);
  const data = await response.json();

  chatList.innerHTML = ""; // empty the list, then build it again

  if (query && data.chats.length === 0) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "No chats match.";
    chatList.appendChild(li);
    return;
  }

  for (const chat of data.chats) {
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

    li.addEventListener("click", () => openChat(chat.id));
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

    li.appendChild(title);
    li.appendChild(edit);
    li.appendChild(del);
    chatList.appendChild(li);
  }
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
  if (id !== currentChatId) recapChat(currentChatId); // NEW (projects step 2)

  const response = await fetch("/chats/" + id);
  const chat = await response.json();

  currentChatId = chat.id;
  history = chat.messages;

  messagesEl.innerHTML = "";
  attachChips.innerHTML = ""; // NEW
  lastUserEl = null;
  for (const message of history) {
    if (message.role === "user") {
      lastUserEl = addMessage("You: " + message.content);
      addImagesTo(lastUserEl, message.images);
      if (message.seen) showSeen(lastUserEl, message.seen);
    } else {
      showReply(addMessage(""), "Cerberus:", message.content);
    }
  }
  showRegenerate();

  loadChats(); // redraw the list, so the open chat is highlighted
  showFeature("chat");
}

// An empty chat. It's only saved on the server when the first message is sent.
function newChat() {
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
  "What do you remember about me?",
  "Write a short poem about a three-headed dog",
];

// The big "Cerberus" in the middle of an empty chat.
function showHome() {
  const home = document.createElement("div");
  home.id = "home";

  const title = document.createElement("h1");
  title.textContent = "Cerberus";

  const tagline = document.createElement("p");
  tagline.className = "tagline";
  tagline.textContent = currentProject
    ? "Project: " + currentProject.name
    : "Your private AI. Everything stays on this computer.";

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

  home.append(title, tagline, suggestions);
  messagesEl.appendChild(home);
}

// Clicking the name in the sidebar: a new, empty chat with the home screen.
document.getElementById("home-button").addEventListener("click", newChat);

async function deleteChat(id) {
  if (!confirm("Delete this chat?")) return;

  await fetch("/chats/" + id, { method: "DELETE" });

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
  if (!currentProject || !chatId || !modelSelect.value) return;

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
async function sendNormal(model) {
  // When the Eyes have to look at an image first, say so: it takes a while.
  const last = history[history.length - 1];
  const looking = last.images && last.images.length > 0 && !last.seen && !visionModels.has(model);
  const bubble = addMessage(looking ? "Cerberus is looking at the image..." : "Cerberus is thinking...");

  let response;
  try {
    response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: history,
        model: model,
        chat_id: currentChatId,
        think: wantsThinking(),
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
    bubble.textContent = "Cerberus: the server answered with error " + response.status + ".";
    return null;
  }

  const who = "Cerberus (" + replyLabel(response.headers) + "):";
  bubble.textContent = who + " ...";

  const result = await readReply(response, bubble, who, (ev) => {
    if (ev.type === "seen") {
      // What the Eyes saw: keep it with the question, so they never
      // have to look at this picture again, and show it.
      history[history.length - 1].seen = ev.text;
      showSeen(lastUserEl, ev.text, ev.model);
    }
  });
  messagesEl.scrollTop = messagesEl.scrollHeight;
  // The server saves a stopped answer too, so we keep it here as well.
  return finishReply(result, bubble, who);
}

// Reads a streamed answer (NDJSON like /chat sends it) into bubble: the
// thinking, the answer, the stats and errors. Event types it doesn't know
// (like "seen") go to onOther. The main chat and the Reverse panel both
// use it. Returns { reply, stats, failure, stopped }.
async function readReply(response, bubble, who, onOther) {
  const result = { reply: "", stats: null, failure: null, stopped: false };
  let thinkBox = null; // the fold-out box, made when the first thought arrives

  try {
    await readEvents(response, (ev) => {
      if (ev.type === "thinking") {
        thinkBox = thinkBox || makeThinkingBox(bubble);
        thinkBox.lastChild.textContent += ev.text;
      } else if (ev.type === "content") {
        // The first word of the answer: thinking is over.
        if (thinkBox && !result.reply) {
          thinkBox.firstChild.textContent = "Show thinking";
        }
        result.reply += ev.text;
        showReply(bubble, who, result.reply);
      } else if (ev.type === "stats") {
        result.stats = ev;
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
  }
  return result;
}

// Shows how an answer ended, and returns its text (null = no answer).
function finishReply(result, bubble, who) {
  if (result.stopped) {
    if (!result.reply) {
      bubble.textContent = "Cerberus: (stopped)";
      return null;
    }
    // Stopped halfway: keep what we have.
    showReply(bubble, who, result.reply + "\n\n*(stopped)*");
    return result.reply;
  }
  if (result.failure) {
    bubble.textContent = "Cerberus: " + result.failure;
    return null;
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
    if (done) break;
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

// A Deep think answer: the draft and the review go in a fold-out box,
// the final answer is shown on top. Returns the final text, or null.
async function sendCouncil(model) {
  const container = document.createElement("div");
  const answer = makeBox("judge", "Cerberus is thinking deeply...");

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

  try {
    const response = await fetch("/council", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: history,
        model: model,
        chat_id: currentChatId,
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      answer.textContent = "Cerberus: the server answered with error " + response.status + ".";
      return null;
    }

    const label = replyLabel(response.headers);

    await readEvents(response, (ev) => {
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

  return failed ? null : texts.final;
}

// Sends one question and shows the answer. The form uses it, and so does
// Regenerate, which is why it's a function of its own.
async function send(text, model, images = [], seen = "") {
  await ensureChat();

  regenButton.remove(); // no Regenerate while an answer is running
  // The first message of a new chat: the home screen makes room for it.
  // "?." = only call remove() if the element exists.
  document.getElementById("home")?.remove();
  lastUserEl = addMessage("You: " + text);
  addImagesTo(lastUserEl, images);
  history.push({ role: "user", content: text, images: images, seen: seen });

  controller = new AbortController();
  sendButton.textContent = "Stop";

  try {
    const reply = threeHeads.checked
      ? await sendCouncil(model)
      : await sendNormal(model);

    if (reply === null) {
      // No answer, so take the question back out of the history too.
      history.pop();
    } else {
      history.push({ role: "assistant", content: reply });
      showRegenerate();
      // First question and answer of this chat, so give it a title.
      // No await: the button is free again right away, and the
      // sidebar shows the title when it arrives.
      if (history.length === 2) makeTitle(model).then(loadChats);
    }
  } catch (error) {
    history.pop();
    addMessage("Cerberus: could not reach the server. Is it running?");
  } finally {
    // finally always runs: after an answer, an error or a Stop.
    controller = null;
    sendButton.textContent = "Send";
  }

  loadChats();
}

// Regenerate: forget the last answer and ask the same question again.
// The model picks its words with some randomness, so the new answer differs.
async function regenerate() {
  const model = modelSelect.value;
  if (controller || !lastUserEl || !model) return;

  // The last two entries in history are the question and its answer.
  // { content, images } = ... takes those two fields out of the object.
  const { content, images, seen } = history[history.length - 2];
  await fetch("/chats/" + currentChatId + "/last-turn", { method: "DELETE" });
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
    controller.abort();
    return;
  }

  const text = input.value.trim();
  if (!text && pendingImages.length === 0) return;

  const model = modelSelect.value;
  if (!model) {
    addMessage("Please pick a model first.");
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
function freeOtherModels() {
  if (!modelSelect.value) return;
  fetch("/models/keep", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: modelSelect.value }),
  })
    .then((response) => response.json())
    .then((data) => {
      if (data.unloaded.length > 0) {
        attachStatus.textContent = "Freed memory: " + data.unloaded.join(", ");
      }
    })
    .catch(() => {
      // Not freeing memory isn't worth an error message.
    });
}

modelSelect.addEventListener("change", freeOtherModels);

// Remember the chosen model for the next visit.
modelSelect.addEventListener("change", () => {
  localStorage.setItem("cerberus-model", modelSelect.value);
  updateModelFeatures();
});

// NEW (projects step 2): closing or reloading the page also leaves the chat.
window.addEventListener("pagehide", () => recapChat(currentChatId));

// ---------- + button (documents) ----------

// documents.js owns the file picker and the upload. It also declares
// documentFile and documentStatus, and all scripts on a page share one
// space, so here we look the elements up by id instead of declaring them again.
attachButton.addEventListener("click", () => {
  document.getElementById("document-file").click();
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

  const name = document.createElement("span");
  name.textContent = "📄 " + doc.name;

  const remove = document.createElement("button");
  remove.type = "button"; // inside a form, a plain button would submit it
  remove.className = "chip-x";
  remove.textContent = "×";
  remove.title = "Remove this document from Cerberus";
  remove.addEventListener("click", async () => {
    await fetch("/documents/" + doc.id, { method: "DELETE" });
    chip.remove();
    attachStatus.textContent = "";
  });

  chip.append(name, remove);
  attachChips.appendChild(chip);
}

// NEW: documents.js announces each finished upload. Show a chip only when
// the upload came from the chat, not from the Memory panel.
document.addEventListener("document-added", (event) => {
  if (document.getElementById("panel-chat").classList.contains("active")) {
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

// ---------- Start ----------

// When the page opens, only the chosen model stays in memory too.
loadModels().then(loadEyes).then(freeOtherModels);
loadChats();
showHome(); // no chat is open yet
