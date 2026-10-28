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

let modelsView = "installed";
let localModelsLoaded = false;
let localModelsRequest = 0;
let libraryLoaded = false;
let hfLoaded = false;
const CAPABILITY_LABELS = {
  vision: "Reads images", tools: "Uses tools", thinking: "Reasoning",
  embedding: "Document search", audio: "Audio", cloud: "Cloud",
};

function loadModelLibrary() {
  if (!document.getElementById("source-local").hidden) {
    if (!localModelsLoaded) loadLocalModels();
  } else if (!document.getElementById("source-huggingface").hidden) {
    if (!hfLoaded && !hfQuery) loadHuggingFace();
  } else if (!libraryLoaded && !libraryQuery) loadLibrary();
}

function showModelsView(view) {
  modelsView = view;
  document.getElementById("models-installed-view").hidden = view !== "installed";
  document.getElementById("models-discover-view").hidden = view !== "discover";
  for (const button of document.querySelectorAll("[data-model-view]")) {
    const selected = button.dataset.modelView === view;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
  }
  if (view === "discover") loadModelLibrary();
}

for (const button of document.querySelectorAll("[data-model-view]")) {
  button.addEventListener("click", () => showModelsView(button.dataset.modelView));
}
document.getElementById("models-browse").addEventListener("click", () => showModelsView("discover"));

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
  span.textContent = CAPABILITY_LABELS[text] || text;
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
    : "Your collection starts here. Choose Find a model to download your first one.";
  installedList.innerHTML = "";
  for (const model of data.models) installedList.appendChild(installedRow(model));
  installedNames = new Set(data.models.map((model) => model.name));
  // Update the ✓ installed marks in both lists.
  if (libraryModels.length) renderLibrary();
  if (hfModels.length) renderHuggingFace();
}

// Opening the panel: the installed models, and the list of the chosen
// source the first time (after that it's already there).
function loadModelsPanel() {
  // Another engine chosen: these models are Ollama's, say so.
  const note = document.getElementById("models-engine-note");
  note.hidden = currentEngine.kind === "ollama"; // app.js
  note.textContent = "Your AI engine is " + currentEngine.name + ": it manages its own models. " +
    "This collection belongs to Ollama. Choose Ollama in Settings → Setup check to chat with these models.";
  loadInstalledModels();
  if (modelsView === "discover") loadModelLibrary();
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
  details.textContent = formatBytes(model.size) ? formatBytes(model.size) + " on disk" : "Downloaded";
  const tags = document.createElement("div");
  tags.className = "tags";
  for (const capability of model.capabilities) {
    if (SHOWN_CAPABILITIES.includes(capability)) tags.appendChild(tag(capability));
  }
  if (model.in_memory) tags.appendChild(tag("Loaded · " + formatBytes(model.in_memory), "tag live"));
  const technical = document.createElement("details");
  technical.className = "model-technical";
  const summary = document.createElement("summary");
  summary.textContent = "Model details";
  technical.append(summary, tag([model.parameters, model.quantization].filter(Boolean).join(" · ") || "No extra details available", "hint"));
  info.append(name, details, tags, technical);

  const actions = document.createElement("div");
  actions.className = "model-actions";
  if (currentEngine.kind === "ollama" && model.capabilities.includes("completion")) {
    const use = document.createElement("button");
    use.type = "button";
    use.className = "primary";
    use.textContent = "Use in chat";
    use.addEventListener("click", () => useInstalledModel(model.name));
    actions.appendChild(use);
  }
  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "Delete";
  remove.addEventListener("click", () => deleteModel(model));

  remove.className = "model-remove";
  remove.setAttribute("aria-label", "Delete " + model.name);
  actions.appendChild(remove);
  li.append(info, actions);
  return li;
}

async function useInstalledModel(name) {
  if (controller || attachmentUploads) {
    installedStatus.textContent = "Finish or stop your current message before changing models.";
    return;
  }
  try {
    await loadModels();
    if (controller || attachmentUploads) throw new Error("Finish or stop your current message before changing models.");
    if (currentEngine.kind !== "ollama") throw new Error("Choose Ollama in Setup to use this model.");
    if (![...modelSelect.options].some((option) => option.value === name)) {
      throw new Error("This model is no longer available. Refresh Your models and try again.");
    }
    modelSelect.value = name;
    modelSelect.dispatchEvent(new Event("change"));
    showFeature("chat");
  } catch (error) {
    installedStatus.textContent = error.message;
  }
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
    libraryLoaded = true;
  } catch (error) {
    libraryModels = [];
    libraryStatus.textContent = error.message + " You can also use Download by model name.";
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
    : "No matches. Try another search or change Filter and sort.";
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
  document.getElementById("download-cancel").disabled = false;
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
    document.getElementById("download-cancel").disabled = true;
  }

  if (done) {
    downloadName.textContent = name + " is installed";
    downloadStatus.textContent = "Ready to use. Open Your models and choose Use in chat.";
    downloadProgress.max = 1;
    downloadProgress.value = 1;
    await loadInstalledModels();
    await loadModels(); // the chat's model list (app.js)
  } else {
    downloadName.textContent = "Not installed: " + name;
    downloadStatus.textContent = failure || "The download ended early. Try again.";
  }
}

// ---------- Models exposed by other running local apps ----------

async function loadLocalModels() {
  const request = ++localModelsRequest;
  const status = document.getElementById("local-models-status");
  const results = document.getElementById("local-models-results");
  const refresh = document.getElementById("local-models-refresh");
  status.textContent = "Looking for local AI apps…";
  refresh.disabled = true;
  results.innerHTML = "";
  try {
    const response = await fetch("/models/local");
    if (!response.ok) throw new Error(await responseError(response));
    const data = await response.json();
    if (request !== localModelsRequest) return;
    localModelsLoaded = true;
    let count = 0;
    for (const engine of data.engines) {
      for (const name of engine.models) {
        results.appendChild(localModelRow(engine, name));
        count++;
      }
    }
    status.textContent = count ? count + (count === 1 ? " model available" : " models available") + " from your local apps."
      : data.engines.length ? "Found a local app, but no models are available yet. Load a model in that app, then refresh."
      : "No local apps found yet. Start a local app's API server, then refresh.";
  } catch (error) {
    if (request === localModelsRequest) status.textContent = error.message;
  } finally {
    if (request === localModelsRequest) refresh.disabled = false;
  }
}

document.getElementById("local-models-refresh").addEventListener("click", loadLocalModels);

function localModelRow(engine, name) {
  const card = document.createElement("li");
  const info = document.createElement("div");
  info.className = "model-info";
  const title = document.createElement("strong");
  title.className = "model-name";
  title.textContent = name;
  info.append(title, tag(engine.name, "tag live"));
  const use = document.createElement("button");
  use.type = "button";
  use.className = "primary";
  use.textContent = "Use in chat";
  use.addEventListener("click", async () => {
    const status = document.getElementById("local-models-status");
    if (controller || attachmentUploads) {
      status.textContent = "Finish or stop your current message before changing engines.";
      return;
    }
    use.disabled = true;
    status.textContent = "Connecting to " + engine.name + "…";
    try {
      const response = await fetch("/setup/engine", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ engine: "openai", preset: engine.preset, url: engine.url, key: "" }) });
      if (!response.ok) throw new Error(await responseError(response));
      const result = await response.json();
      if (!result.ok) throw new Error(result.error);
      await loadModels();
      if (controller || attachmentUploads) throw new Error("Finish or stop your current message before changing models.");
      if (![...modelSelect.options].some(option => option.value === name)) throw new Error("This model is not available for chat. Load a chat model in the app, then refresh.");
      modelSelect.value = name;
      modelSelect.dispatchEvent(new Event("change"));
      showFeature("chat");
      status.textContent = "Connected to " + engine.name + ".";
    } catch (error) {
      status.textContent = error.message;
    } finally {
      use.disabled = false;
    }
  });
  card.append(info, use);
  return card;
}

// ---------- Where models come from: the Ollama library or Hugging Face ----------

for (const button of document.querySelectorAll("#model-source [data-source]")) {
  button.addEventListener("click", () => showSource(button.dataset.source));
}

function showSource(source) {
  for (const other of document.querySelectorAll("#model-source [data-source]")) {
    other.classList.toggle("active", other.dataset.source === source);
    other.setAttribute("aria-pressed", String(other.dataset.source === source));
  }
  document.getElementById("source-local").hidden = source !== "local";
  document.getElementById("source-ollama").hidden = source !== "ollama";
  document.getElementById("source-huggingface").hidden = source !== "huggingface";
  // The Hugging Face list loads the first time you open it.
  if (modelsView === "discover") loadModelLibrary();
  // Remember the choice for next time (this browser only).
  try {
    localStorage.setItem("cerberus-model-source", source);
  } catch (_) { /* private mode: just don't remember */ }
}

// Ollama may write a name with other capitals than Hugging Face, so the
// "already installed" check ignores case.
function isInstalled(name) {
  const wanted = name.toLowerCase();
  return [...installedNames].some((installed) => installed.toLowerCase() === wanted);
}

// ---------- Hugging Face ----------

const hfResults = document.getElementById("hf-results");
const hfStatus = document.getElementById("hf-status");

// The Hugging Face list, like the Ollama one: what came, and what's shown.
let hfModels = [];
let hfOrder = "popular"; // popular, trending, liked
let hfCategory = "chat"; // chat, vision, embedding
let hfShown = 0;
let hfQuery = ""; // the search words, "" = browsing

// The versions most people choose from. The others (IQ2_M, Q4_0_4_8...)
// are for experts, one click away under "Show all".
const COMMON_VERSIONS = ["Q3_K_M", "Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0"];

function commonVersions(versions) {
  const common = versions.filter((item) => COMMON_VERSIONS.includes(item.version));
  return common.length ? common : versions; // an unusual model: show them all
}

// 1234567 -> "1.2M"
function compactNumber(number) {
  return new Intl.NumberFormat("en", { notation: "compact" }).format(number);
}

// Without words: browse the chosen order and category. With words: search.
async function loadHuggingFace(query = "") {
  hfQuery = query;
  hfResults.innerHTML = "";
  document.getElementById("hf-more").hidden = true;
  hfStatus.textContent = query ? "Searching Hugging Face…" : "Loading from Hugging Face…";
  const params = new URLSearchParams(query ? { q: query } : { order: hfOrder, category: hfCategory });
  try {
    const response = await fetch("/models/huggingface?" + params);
    if (!response.ok) throw new Error(await responseError(response));
    hfModels = (await response.json()).models;
    hfLoaded = true;
  } catch (error) {
    hfModels = [];
    hfStatus.textContent = error.message;
    return;
  }
  hfShown = LIBRARY_PAGE;
  renderHuggingFace();
}

const HF_ORDER_WORDS = { popular: "most downloaded", trending: "trending now", liked: "most liked" };

function renderHuggingFace() {
  hfStatus.textContent = !hfModels.length
    ? "Nothing found. Try fewer or other words."
    : hfQuery
    ? hfModels.length + " GGUF models found, most downloaded first. Choose a version to download."
    : hfModels.length + " " + hfCategory + " models, " + HF_ORDER_WORDS[hfOrder] + " first. Choose a version to download.";
  hfResults.innerHTML = "";
  for (const model of hfModels.slice(0, hfShown)) hfResults.appendChild(hfRow(model));
  const more = document.getElementById("hf-more");
  const left = hfModels.length - hfShown;
  more.hidden = left <= 0;
  more.textContent = "Show more (" + left + " left)";
}

document.getElementById("hf-search").addEventListener("submit", (event) => {
  event.preventDefault();
  // Empty search: back to browsing.
  loadHuggingFace(document.getElementById("hf-query").value.trim());
});

document.getElementById("hf-more").addEventListener("click", () => {
  hfShown += LIBRARY_PAGE;
  renderHuggingFace();
});

// Popular / Trending / Most liked, and Chat / Vision / Embedding: each a
// new list from Hugging Face (the server keeps each one an hour).
function hfChoice(selector, key, apply) {
  for (const button of document.querySelectorAll(selector)) {
    button.addEventListener("click", () => {
      apply(button.dataset[key]);
      for (const other of document.querySelectorAll(selector)) other.classList.toggle("active", other === button);
      document.getElementById("hf-query").value = "";
      loadHuggingFace();
    });
  }
}
hfChoice("#hf-order [data-order]", "order", (order) => { hfOrder = order; });
hfChoice("#hf-category [data-category]", "category", (category) => { hfCategory = category; });

// Is some version of this Hugging Face model installed? Ollama knows
// them as "hf.co/<repo>:<version>".
function repoInstalled(repo) {
  const prefix = ("hf.co/" + repo + ":").toLowerCase();
  return [...installedNames].some((name) => name.toLowerCase().startsWith(prefix));
}

// One Hugging Face model. Its versions load when you ask for them: that's
// one more request to Hugging Face, so not for all 20 results at once.
function hfRow(model) {
  const li = document.createElement("li");
  const info = document.createElement("div");
  info.className = "model-info";

  const head = document.createElement("div");
  head.className = "model-head";
  const name = document.createElement("strong");
  name.className = "model-name";
  name.textContent = model.repo;
  head.append(name, tag(compactNumber(model.downloads) + " downloads · " + compactNumber(model.likes) + " likes", "hint"));

  const tags = document.createElement("div");
  tags.className = "tags";
  if (model.vision) tags.appendChild(tag("vision"));
  if (model.embedding) tags.appendChild(tag("embedding"));
  if (repoInstalled(model.repo)) tags.appendChild(tag("installed", "tag live"));

  const versions = document.createElement("div");
  versions.className = "sizes";
  const choose = document.createElement("button");
  choose.type = "button";
  choose.textContent = "Choose version";
  choose.addEventListener("click", () => loadVersions(model.repo, versions, tags));
  versions.appendChild(choose);

  info.append(head, tags, versions);
  li.appendChild(info);
  return li;
}

async function loadVersions(repo, box, tags) {
  box.innerHTML = "";
  box.appendChild(tag("Loading versions…", "hint"));
  let data;
  try {
    const response = await fetch("/models/huggingface/versions?repo=" + encodeURIComponent(repo));
    if (!response.ok) throw new Error(await responseError(response));
    data = await response.json();
  } catch (error) {
    box.innerHTML = "";
    box.appendChild(tag(error.message, "hint"));
    return;
  }
  box.innerHTML = "";
  if (data.license) tags.appendChild(tag("license: " + data.license));
  if (data.gated) {
    box.appendChild(tag("Gated: this model needs a Hugging Face account and accepted terms, so it " +
                        "can't be downloaded here. Look for another publisher's GGUF of it.", "hint"));
    return;
  }
  if (!data.versions.length) {
    box.appendChild(tag("No GGUF files in this model, so Ollama can't run it.", "hint"));
    return;
  }

  // First the common versions; "Show all" adds the rest.
  function draw(versions) {
    box.innerHTML = "";
    for (const item of versions) box.appendChild(versionButton(item, data.suggested));
    if (versions.length < data.versions.length) {
      const all = document.createElement("button");
      all.type = "button";
      all.textContent = "Show all " + data.versions.length + " versions";
      all.addEventListener("click", () => draw(data.versions));
      box.appendChild(all);
    }
  }
  draw(commonVersions(data.versions));
}

// One version: "★ Q4_K_M · 4.4 GB". The star marks the suggested one.
function versionButton(item, suggested) {
  const button = document.createElement("button");
  button.type = "button";
  const label = item.version + " · " + formatBytes(item.size);
  if (isInstalled(item.ollama_name)) {
    button.textContent = "✓ " + label;
    button.title = "Installed";
    button.disabled = true;
    button.classList.add("installed");
  } else {
    button.textContent = (item.version === suggested ? "★ " : "↓ ") + label;
    button.title = "Download " + item.ollama_name + (item.version === suggested ? " (suggested)" : "");
    if (item.version === suggested) button.classList.add("suggested");
    button.addEventListener("click", () => startDownload(item.ollama_name));
  }
  return button;
}

// ---------- Start ----------

// The source used last time. At the very end of the file on purpose: it
// uses variables declared above (hfModels...), and JavaScript doesn't
// allow a "let" variable to be used before its line has run.
try {
  const saved = localStorage.getItem("cerberus-model-source");
  if (["huggingface", "local"].includes(saved)) showSource(saved);
} catch (_) { /* nothing remembered */ }
