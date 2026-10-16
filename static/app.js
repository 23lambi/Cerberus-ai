const form = document.getElementById("chat-form");
const input = document.getElementById("input");
const messagesEl = document.getElementById("messages");
const modelSelect = document.getElementById("model");
const threeHeads = document.getElementById("three-heads");
const chatList = document.getElementById("chat-list");
const newChatButton = document.getElementById("new-chat");
const sendButton = document.getElementById("send");
const attachButton = document.getElementById("attach");
const attachStatus = document.getElementById("attach-status");

// NEW: the row of file chips, created here and placed right above the message box.
const attachChips = document.createElement("div");
attachChips.id = "attach-chips";
form.before(attachChips);

const ERROR_MARK = "[Cerberus error]";

const MODE_NAMES = {
  chat: "Chat",
  memory: "Memory",
};

const STEP_LABELS = {
  draft: "Draft",
  review: "Review",
};

let history = [];
let currentChatId = null;
let currentProject = null;
// The "remote control" that cancels the running request. null = nothing running.
let controller = null;

// ---------- Helpers ----------

function sourceLabels(headers) {
  const kinds = [
    ["X-Cerberus-Memories", "memory", "memories"],
    ["X-Cerberus-Documents", "document part", "document parts"],
    ["X-Cerberus-Chats", "old chat message", "old chat messages"],
  ];
  const labels = [];
  for (const [header, one, many] of kinds) {
    const count = Number(headers.get(header) || 0);
    if (count) labels.push(count + " " + (count === 1 ? one : many));
  }
  return labels;
}

function addMessage(text) {
  const p = document.createElement("p");
  p.textContent = text;
  messagesEl.appendChild(p);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return p;
}

function makeBox(className, text) {
  const div = document.createElement("div");
  div.className = className;
  div.textContent = text;
  return div;
}

// ---------- Models ----------

async function loadModels() {
  const response = await fetch("/models");
  const data = await response.json();

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
}

// ---------- Chat list ----------

async function loadChats() {
  const response = await fetch(currentProject ? "/chats?project_id=" + currentProject.id : "/chats");
  const data = await response.json();

  chatList.innerHTML = "";

  for (const chat of data.chats) {
    const li = document.createElement("li");
    if (chat.id === currentChatId) {
      li.className = "active";
    }

    const title = document.createElement("span");
    title.className = "title";
    title.textContent = chat.title;

    const del = document.createElement("button");
    del.className = "delete";
    del.textContent = "x";
    del.title = "Delete chat";

    li.addEventListener("click", () => openChat(chat.id));
    del.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteChat(chat.id);
    });

    li.appendChild(title);
    li.appendChild(del);
    chatList.appendChild(li);
  }
}

async function openChat(id) {
  if (id !== currentChatId) recapChat(currentChatId); // NEW (projects step 2)

  const response = await fetch("/chats/" + id);
  const chat = await response.json();

  currentChatId = chat.id;
  history = chat.messages;

  messagesEl.innerHTML = "";
  attachChips.innerHTML = ""; // NEW
  for (const message of history) {
    const who = message.role === "user" ? "You: " : "Cerberus: ";
    addMessage(who + message.content);
  }

  loadChats();
  showFeature("chat");
}

function newChat() {
  recapChat(currentChatId); // NEW (projects step 2)
  currentChatId = null;
  history = [];
  messagesEl.innerHTML = "";
  attachStatus.textContent = "";
  attachChips.innerHTML = ""; // NEW: chips go, the documents stay in Memory
  loadChats();
  showFeature("chat");
  input.focus();
}

async function deleteChat(id) {
  if (!confirm("Delete this chat?")) return;

  await fetch("/chats/" + id, { method: "DELETE" });

  if (id === currentChatId) {
    newChat();
  } else {
    loadChats();
  }
}

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

async function sendNormal(model) {
  const bubble = addMessage("Cerberus is thinking...");

  let response;
  try {
    response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: history,
        model: model,
        chat_id: currentChatId,
      }),
      signal: controller.signal,
    });
  } catch (error) {
    if (error.name !== "AbortError") throw error;
    bubble.textContent = "Cerberus: (stopped)";
    return null;
  }

  if (!response.ok) {
    bubble.textContent = "Cerberus: the server answered with error " + response.status + ".";
    return null;
  }

  const mode = MODE_NAMES[response.headers.get("X-Cerberus-Mode")] || "Chat";
  const label = [mode, ...sourceLabels(response.headers)].join(", ");
  bubble.textContent = "Cerberus (" + label + ") is thinking...";

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let reply = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      reply += decoder.decode(value, { stream: true });
      bubble.textContent = "Cerberus (" + label + "): " + reply;
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  } catch (error) {
    if (error.name !== "AbortError") throw error;
    if (!reply) {
      bubble.textContent = "Cerberus: (stopped)";
      return null;
    }
    bubble.textContent = "Cerberus (" + label + "): " + reply + " (stopped)";
    return reply;
  }

  const errorAt = reply.indexOf(ERROR_MARK);
  if (errorAt !== -1) {
    bubble.textContent = "Cerberus: " + reply.slice(errorAt + ERROR_MARK.length).trim();
    return null;
  }

  return reply;
}

async function sendCouncil(model) {
  const container = document.createElement("div");
  const answer = makeBox("judge", "Cerberus is thinking deeply...");

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

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.trim()) continue;
        const ev = JSON.parse(line);

        if (ev.step === "error") {
          answer.textContent = "Cerberus: " + ev.text;
          failed = true;
          continue;
        }

        texts[ev.step] += ev.text;

        if (ev.step === "final") {
          answer.textContent = "Cerberus: " + texts.final;
        } else {
          boxes[ev.step].textContent = STEP_LABELS[ev.step] + ": " + texts[ev.step];
          answer.textContent = "Cerberus is writing its " + STEP_LABELS[ev.step].toLowerCase() + "...";
        }
      }
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  } catch (error) {
    if (error.name !== "AbortError") throw error;
    answer.textContent = "Cerberus: (stopped)";
    return null;
  }

  return failed ? null : texts.final;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  // One button, two jobs. If an answer is running, a click means Stop.
  if (controller) {
    controller.abort();
    return;
  }

  const text = input.value.trim();
  if (!text) return;

  const model = modelSelect.value;
  if (!model) {
    addMessage("Please pick a model first.");
    return;
  }

  input.value = "";
  await ensureChat();

  addMessage("You: " + text);
  history.push({ role: "user", content: text });

  controller = new AbortController();
  sendButton.textContent = "Stop";

  try {
    const reply = threeHeads.checked
      ? await sendCouncil(model)
      : await sendNormal(model);

    if (reply === null) {
      history.pop();
    } else {
      history.push({ role: "assistant", content: reply });
      // First question and answer of this chat, so give it a title.
      if (history.length === 2) await makeTitle(model);
    }
  } catch (error) {
    history.pop();
    addMessage("Cerberus: could not reach the server. Is it running?");
  } finally {
    controller = null;
    sendButton.textContent = "Send";
  }

  loadChats();
});

newChatButton.addEventListener("click", newChat);

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
  remove.type = "button";
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

// ---------- Start ----------

loadModels();
loadChats();

