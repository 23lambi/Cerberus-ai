// The Models panel: the installed models, searching the Ollama library,
// and downloading or deleting models. The server does the work
// (cerberus/routes/models.py); this file only shows it.

const installedList = document.getElementById("installed-models");
const installedStatus = document.getElementById("installed-status");
const libraryResults = document.getElementById("library-results");
const libraryStatus = document.getElementById("library-status");
const downloadBox = document.getElementById("model-download");
const downloadName = document.getElementById("download-name");
const downloadStatus = document.getElementById("download-status");
const downloadProgress = document.getElementById("download-progress");

// The running download, so Cancel can stop it. null = none running.
let downloadController = null;

// The library list: what ollama.com sent, and how it's shown right now.
let libraryModels = [];
let libraryOrder = "popular"; // or "newest"
let libraryFilter = "all"; // all, chat, vision, tools, thinking, embedding
let libraryShown = 0; // how many are on screen; "Show more" adds a page
let libraryQuery = ""; // the search words, "" = browsing
let installedNames = new Set(); // to mark sizes you already have
const LIBRARY_PAGE = 30;

// What a model can do, shown as small tags. "completion" (it can chat)
// is true for almost every model, so it isn't shown.
const SHOWN_CAPABILITIES = ["vision", "tools", "thinking", "embedding", "audio", "cloud"];

// 2013265920 -> "1.9 GB"
function formatBytes(bytes) {
  if (!bytes) return "";
  const units = ["bytes", "KB", "MB", "GB", "TB"];
  let size = bytes;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit++;
  }
  return (unit ? size.toFixed(1) : size) + " " + units[unit];
}

function tag(text, className = "tag") {
  const span = document.createElement("span");
  span.className = className;
  span.textContent = text;
  return span;
}

// ---------- Installed models ----------

async function loadInstalledModels() {
  installedStatus.textContent = "Loading…";
  let data;
  try {
    const response = await fetch("/models/installed");
    if (!response.ok) throw new Error(await responseError(response));
    data = await response.json();
  } catch (error) {
    installedStatus.textContent = error.message;
    return;
  }
  installedStatus.textContent = data.models.length
    ? ""
    : "No models yet. Pick one below, or type a name like llama3.2:3b.";
  installedList.innerHTML = "";
  for (const model of data.models) installedList.appendChild(installedRow(model));
  installedNames = new Set(data.models.map((model) => model.name));
  if (libraryModels.length) renderLibrary(); // update the ✓ installed marks
}

// Opening the panel: the installed models, and the library list the
// first time (after that it's already there).
function loadModelsPanel() {
  loadInstalledModels();
  if (!libraryModels.length && !libraryQuery) loadLibrary();
}

// One installed model: name, details, what it can do, and Delete.
function installedRow(model) {
  const li = document.createElement("li");

  const info = document.createElement("div");
  info.className = "model-info";
  const name = document.createElement("strong");
  name.className = "model-name";
  name.textContent = model.name;
  const details = document.createElement("p");
  details.className = "hint";
  // "3.2B · Q4_K_M · 1.9 GB": parameters, how it's compressed, size on disk.
  details.textContent = [model.parameters, model.quantization, formatBytes(model.size)].filter(Boolean).join(" · ");
  const tags = document.createElement("div");
  tags.className = "tags";
  for (const capability of model.capabilities) {
    if (SHOWN_CAPABILITIES.includes(capability)) tags.appendChild(tag(capability));
  }
  if (model.in_memory) tags.appendChild(tag("in memory · " + formatBytes(model.in_memory), "tag live"));
  info.append(name, details, tags);

  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "Delete";
  remove.addEventListener("click", () => deleteModel(model));

  li.append(info, remove);
  return li;
}

async function deleteModel(model) {
  if (!confirm("Delete " + model.name + "? It frees " + formatBytes(model.size) +
               " of disk space. You can download it again later.")) return;
  // The name goes in the address; encodeURIComponent keeps "/" and ":" safe.
  const response = await fetch("/models/installed?name=" + encodeURIComponent(model.name), { method: "DELETE" });
  if (!response.ok) {
    installedStatus.textContent = await responseError(response);
    return;
  }
  await loadInstalledModels();
  await loadModels(); // the chat's model list (app.js)
}

// ---------- The Ollama library: browse or search ----------

// Without words: the Popular or Newest list. With words: a search.
async function loadLibrary(query = "") {
  libraryQuery = query;
  libraryResults.innerHTML = "";
  document.getElementById("library-more").hidden = true;
  libraryStatus.textContent = query ? "Searching ollama.com…" : "Loading the Ollama library…";
  const params = new URLSearchParams(query ? { q: query } : { order: libraryOrder });
  try {
    const response = await fetch("/models/library?" + params);
    if (!response.ok) throw new Error(await responseError(response));
    libraryModels = (await response.json()).models;
  } catch (error) {
    libraryModels = [];
    libraryStatus.textContent = error.message + " You can still type an exact name above.";
    return;
  }
  libraryShown = LIBRARY_PAGE;
  renderLibrary();
}

// Does a model belong in the chosen filter? "chat" = everything that can
// talk, so every model except the embedding ones.
function matchesFilter(model, filter) {
  if (filter === "all") return true;
  if (filter === "chat") return !model.capabilities.includes("embedding");
  return model.capabilities.includes(filter);
}

// Draws the list: the chosen filter, one page at a time.
function renderLibrary() {
  const matching = libraryModels.filter((model) => matchesFilter(model, libraryFilter));
  const where = libraryQuery ? "found" : libraryOrder === "newest" ? "new on Ollama" : "on Ollama, most popular first";
  libraryStatus.textContent = matching.length
    ? matching.length + " models " + where + ". Pick a size to download it."
    : "Nothing here. Try another filter, or type an exact name above.";
  libraryResults.innerHTML = "";
  for (const model of matching.slice(0, libraryShown)) libraryResults.appendChild(libraryRow(model));
  const more = document.getElementById("library-more");
  const left = matching.length - libraryShown;
  more.hidden = left <= 0;
  more.textContent = "Show more (" + left + " left)";
}

document.getElementById("library-search").addEventListener("submit", (event) => {
  event.preventDefault();
  // Empty search: back to browsing.
  loadLibrary(document.getElementById("library-query").value.trim());
});

document.getElementById("library-more").addEventListener("click", () => {
  libraryShown += LIBRARY_PAGE;
  renderLibrary();
});

// Popular / Newest: a new list from ollama.com (the server keeps it an hour).
for (const button of document.querySelectorAll("#library-order [data-order]")) {
  button.addEventListener("click", () => {
    libraryOrder = button.dataset.order;
    for (const other of document.querySelectorAll("#library-order [data-order]")) {
      other.classList.toggle("active", other === button);
    }
    document.getElementById("library-query").value = "";
    loadLibrary();
  });
}

// The filters only change what's shown: no new request.
for (const button of document.querySelectorAll("#library-filter [data-filter]")) {
  button.addEventListener("click", () => {
    libraryFilter = button.dataset.filter;
    for (const other of document.querySelectorAll("#library-filter [data-filter]")) {
      other.classList.toggle("active", other === button);
    }
    libraryShown = LIBRARY_PAGE;
    renderLibrary();
  });
}

// "qwen3" + "4b" -> "qwen3:4b". Without a size Ollama installs ":latest".
function fullName(name, size) {
  return name + ":" + (size || "latest");
}

// One search result: name, description, tags, and a button per size.
function libraryRow(model) {
  const li = document.createElement("li");
  const info = document.createElement("div");
  info.className = "model-info";

  const head = document.createElement("div");
  head.className = "model-head";
  const name = document.createElement("strong");
  name.className = "model-name";
  name.textContent = model.name;
  head.appendChild(name);
  if (model.downloads) head.appendChild(tag(model.downloads + " downloads", "hint"));

  const description = document.createElement("p");
  description.className = "model-description";
  description.textContent = model.description;

  const tags = document.createElement("div");
  tags.className = "tags";
  for (const capability of model.capabilities) tags.appendChild(tag(capability));

  // One button per size: "4b" downloads "qwen3:4b". No sizes listed:
  // download the default ("latest").
  const sizes = document.createElement("div");
  sizes.className = "sizes";
  for (const size of model.sizes.length ? model.sizes : [null]) {
    const button = document.createElement("button");
    button.type = "button";
    const name = fullName(model.name, size);
    if (installedNames.has(name)) {
      // Already here: nothing to download.
      button.textContent = "✓ " + (size || "installed");
      button.title = name + " is installed";
      button.disabled = true;
      button.classList.add("installed");
    } else {
      button.textContent = size ? "↓ " + size : "↓ Download";
      button.title = "Download " + name;
      button.addEventListener("click", () => startDownload(name));
    }
    sizes.appendChild(button);
  }
  info.append(head, description, tags, sizes);
  if (model.capabilities.includes("cloud") && !model.sizes.length) {
    info.appendChild(tag("A cloud model: it runs on Ollama's servers, not on this computer.", "hint"));
  }
  li.appendChild(info);
  return li;
}

// ---------- Downloading ----------

document.getElementById("pull-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const name = document.getElementById("pull-name").value.trim();
  if (name) startDownload(name);
});

document.getElementById("download-cancel").addEventListener("click", () => {
  if (downloadController) downloadController.abort();
});

// Ollama's steps in plain words.
function downloadStepText(ev) {
  const status = ev.status || "";
  let text = status;
  if (status === "pulling manifest") text = "Getting the list of files";
  else if (status.startsWith("pulling ")) text = "Downloading";
  else if (status.startsWith("verifying")) text = "Checking the download";
  else if (status === "writing manifest") text = "Finishing";
  else if (status === "success") text = "Done";
  if (ev.total) {
    const done = ev.completed || 0;
    const percent = Math.floor((100 * done) / ev.total);
    text += ": " + formatBytes(done) + " of " + formatBytes(ev.total) + " (" + percent + "%)";
  }
  return text;
}

async function startDownload(name) {
  downloadBox.hidden = false;
  if (downloadController) {
    downloadStatus.textContent = "One download at a time: wait for this one, or cancel it.";
    return;
  }
  downloadController = new AbortController();
  downloadName.textContent = "Downloading " + name;
  downloadStatus.textContent = "Starting…";
  downloadProgress.removeAttribute("value"); // no value = a moving "busy" bar

  let done = false;
  let failure = null;
  try {
    const response = await fetch("/models/pull", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: name }),
      signal: downloadController.signal,
    });
    if (!response.ok) throw new Error(await responseError(response));
    // The same NDJSON reader as the chat (app.js).
    await readEvents(response, (ev) => {
      if (ev.type === "progress") {
        downloadStatus.textContent = downloadStepText(ev);
        if (ev.total) {
          downloadProgress.max = ev.total;
          downloadProgress.value = ev.completed || 0;
        }
      } else if (ev.type === "done") {
        done = true;
      } else if (ev.type === "error") {
        failure = ev.text;
      }
    });
  } catch (error) {
    failure = error.name === "AbortError"
      ? "Cancelled. Downloading it again continues where it stopped."
      : error.message;
  } finally {
    downloadController = null;
  }

  if (done) {
    downloadName.textContent = name + " is installed";
    downloadStatus.textContent = "Pick it in the model list next to Send.";
    downloadProgress.max = 1;
    downloadProgress.value = 1;
    await loadInstalledModels();
    await loadModels(); // the chat's model list (app.js)
  } else {
    downloadName.textContent = "Not installed: " + name;
    downloadStatus.textContent = failure || "The download ended early. Try again.";
  }
}
