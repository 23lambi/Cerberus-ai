// The Setup window: is everything Cerberus needs ready, and if not, fix it
// from here. Three steps: the AI engine (Ollama), the models, web search.
// The server checks (cerberus/setup.py); this file shows the result and
// the buttons that make sense for it.

const setupDialog = document.getElementById("setup-dialog");
const setupBody = document.getElementById("setup-body");
let setupBusy = false; // a download is running: don't redraw over it

async function openSetup() {
  if (!setupDialog.open) setupDialog.showModal();
  await renderSetup();
}

// Asks the server what's ready, then draws the three steps.
async function renderSetup() {
  if (setupBusy) return;
  setupBody.innerHTML = "";
  setupBody.appendChild(makeBox("hint", "Checking…"));
  let state;
  try {
    // Both at the same time: what's ready, and the engines to choose from.
    const [statusResponse, enginesResponse] = await Promise.all([fetch("/setup/status"), fetch("/setup/engines")]);
    if (!statusResponse.ok) throw new Error(await responseError(statusResponse));
    state = await statusResponse.json();
    state.engines = await enginesResponse.json();
  } catch (error) {
    setupBody.innerHTML = "";
    setupBody.appendChild(makeBox("hint", "Could not reach Cerberus: " + error.message));
    return;
  }
  setupBody.innerHTML = "";
  const intro = makeBox("hint", "Cerberus needs an AI engine and a model. Web search is optional.");
  setupBody.append(intro, engineStep(state), modelsStep(state), searchStep(state));
}

// ---------- Building blocks ----------

// A step card: a number, a title, and a badge saying how it's going.
function setupStep(number, title, ok, okText = "Ready", todoText = "Needs attention") {
  const card = document.createElement("section");
  card.className = "setup-step";
  const head = document.createElement("div");
  head.className = "setup-step-head";
  const badge = document.createElement("span");
  badge.className = "setup-badge " + (ok ? "ok" : "todo");
  badge.textContent = ok ? "✓ " + okText : "! " + todoText;
  const heading = document.createElement("h3");
  heading.textContent = number + ". " + title;
  head.append(heading, badge);
  card.appendChild(head);
  return card;
}

function setupButton(text, onClick, primary = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = text;
  if (primary) button.className = "primary";
  button.addEventListener("click", onClick);
  return button;
}

// A command to type in a terminal, with a Copy button.
function commandLine(command) {
  const row = document.createElement("div");
  row.className = "setup-command";
  const code = document.createElement("code");
  code.textContent = command;
  const copy = setupButton("Copy", async () => {
    try {
      await navigator.clipboard.writeText(command);
      copy.textContent = "Copied!";
    } catch (_) {
      copy.textContent = "Select and copy it";
    }
    setTimeout(() => (copy.textContent = "Copy"), 1500);
  });
  row.append(code, copy);
  return row;
}

// A progress bar with a line of text under it.
function progressRow(card) {
  const bar = document.createElement("progress");
  bar.className = "progress-bar";
  const text = makeBox("hint", "Starting…");
  card.append(bar, text);
  return { bar, text };
}

// Streams NDJSON steps from the server (like a model download) into a
// progress row. Returns the last step.
async function streamSteps(url, body, row, describe) {
  let last = null;
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(await responseError(response));
  await readEvents(response, (step) => {
    last = step;
    if (step.total) {
      row.bar.max = step.total;
      row.bar.value = step.completed || 0;
    } else {
      row.bar.removeAttribute("value"); // a moving "busy" bar
    }
    row.text.textContent = describe(step);
  });
  return last;
}

// ---------- 1. The AI engine ----------

// Is an address on the internet (not this computer or the home network)?
// The server decides for real; this is for the warning while choosing.
function isCloudAddress(url) {
  let host;
  try {
    host = new URL(url).hostname;
  } catch (_) {
    return false;
  }
  return !(host === "localhost" || host === "::1" || host === "[::1]" ||
           /^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host));
}

function engineStep(state) {
  const card = setupStep(1, "AI engine", state.engine.running);
  const engines = state.engines;

  // The choice: Ollama, or one of the OpenAI-compatible engines.
  const choose = document.createElement("select");
  choose.setAttribute("aria-label", "AI engine");
  choose.appendChild(new Option("Ollama (on this computer)", "ollama"));
  for (const [key, preset] of Object.entries(engines.presets)) choose.appendChild(new Option(preset.name, key));
  choose.value = engines.engine === "ollama" ? "ollama" : engines.openai.preset;
  card.appendChild(choose);

  const details = document.createElement("div");
  details.className = "setup-engine";
  card.appendChild(details);
  const draw = () => {
    details.innerHTML = "";
    if (choose.value === "ollama") ollamaDetails(details, state, engines.engine === "ollama");
    else otherEngineDetails(details, state, engines, choose.value);
  };
  choose.addEventListener("change", draw);
  draw();
  return card;
}

// Saves the engine choice and tests it; then everything updates.
async function useEngine(body, details) {
  details.appendChild(makeBox("hint", "Connecting…"));
  const response = await fetch("/setup/engine", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const result = response.ok ? await response.json() : { ok: false, error: await responseError(response) };
  if (!result.ok) {
    details.lastChild.textContent = result.error;
    return;
  }
  await afterEngineChange();
}

// An OpenAI-compatible engine: address, key, help, and the cloud warning.
function otherEngineDetails(details, state, engines, preset) {
  const info = engines.presets[preset];
  const chosen = engines.engine === "openai" && engines.openai.preset === preset;
  if (chosen) {
    details.appendChild(makeBox("hint", state.engine.running
      ? "✓ Connected to " + state.engine.name + ": " + state.engine.models.length + " models."
      : state.engine.error));
  }
  details.appendChild(makeBox("hint", info.key_help));

  const address = document.createElement("input");
  address.type = "url";
  address.placeholder = "Address, like http://127.0.0.1:1234/v1";
  address.value = chosen ? engines.openai.url : info.url;
  address.setAttribute("aria-label", "Engine address");

  const key = document.createElement("input");
  key.type = "password"; // shown as dots, like any password
  key.autocomplete = "off";
  key.placeholder = chosen && engines.openai.key_set ? "A key is saved (type a new one to replace it)"
    : info.key ? "API key (needed)" : "API key (only if it needs one)";
  key.setAttribute("aria-label", "API key");

  const warning = makeBox("hint engine-cloud", "");
  const updateWarning = () => {
    warning.hidden = !isCloudAddress(address.value);
    warning.textContent = "☁ A cloud engine: your messages are sent to " + info.name.replace(" (cloud)", "") +
      ". Search by meaning stays on this computer.";
  };
  address.addEventListener("input", updateWarning);
  updateWarning();

  details.append(address, key, warning, setupButton(chosen ? "Save & test" : "Use this engine", () =>
    useEngine({ engine: "openai", preset, url: address.value.trim(), key: key.value.trim() }, details), true));
}

// Ollama: what it was before, plus a button to switch back to it.
function ollamaDetails(details, state, chosen) {
  const engine = state.ollama;
  if (!chosen) {
    details.appendChild(makeBox("hint", "Ollama runs models on this computer: private, works offline."));
    details.appendChild(setupButton("Use Ollama", () => useEngine({ engine: "ollama" }, details), true));
    return;
  }
  const card = details;
  if (engine.running) {
    const source = engine.managed ? "Cerberus's own copy" : "installed on this computer";
    card.appendChild(makeBox("hint", "Ollama " + engine.version + " is running (" + source + ")."));
    return;
  }
  if (engine.managed) {
    card.appendChild(makeBox("hint", "Cerberus has its own Ollama, but it isn't running."));
    card.appendChild(setupButton("Start Ollama", () => startOllama(card), true));
  } else if (engine.system) {
    // A system Ollama: started by its own service, not by Cerberus (else
    // it would look for your models in another folder).
    card.appendChild(makeBox("hint", "Ollama is installed but not running. Start it, then press Check again:"));
    card.appendChild(commandLine(engine.start_hint));
  } else if (engine.can_download) {
    card.appendChild(makeBox("hint",
      "Ollama is not installed. Cerberus can download the official version and run it for you: " +
      "no installer, no admin rights. It's about 1.5 GB (220 MB on a Mac), once."));
    card.appendChild(setupButton("Download & run Ollama", () => downloadOllama(card), true));
  } else {
    card.appendChild(makeBox("hint", "Install Ollama from ollama.com/download, then press Check again."));
  }
}

async function startOllama(card) {
  const row = progressRow(card);
  row.text.textContent = "Starting Ollama…";
  const response = await fetch("/setup/ollama/start", { method: "POST" });
  if (!response.ok) {
    row.text.textContent = await responseError(response);
    return;
  }
  await afterEngineChange();
}

async function downloadOllama(card) {
  setupBusy = true;
  for (const button of card.querySelectorAll("button")) button.disabled = true;
  const row = progressRow(card);
  try {
    const last = await streamSteps("/setup/ollama/download", null, row, (step) => {
      if (step.step === "download") {
        const percent = step.total ? Math.floor((100 * step.completed) / step.total) : 0;
        return "Downloading Ollama: " + formatBytes(step.completed) + " of " + formatBytes(step.total) + " (" + percent + "%)";
      }
      if (step.step === "unpack") return "Unpacking… (this takes a moment)";
      if (step.step === "starting") return "Starting Ollama…";
      if (step.step === "running") return "Ollama is running.";
      if (step.step === "error") return step.text;
      return "";
    });
    if (last && last.step === "error") return; // the text already says why
  } catch (error) {
    row.text.textContent = error.message;
    return;
  } finally {
    setupBusy = false;
  }
  await afterEngineChange();
}

// Ollama runs now: the chat's model list can load, and the steps update.
async function afterEngineChange() {
  await loadModels(); // app.js
  await renderSetup();
}

// ---------- 2. Models ----------

function modelsStep(state) {
  const ready = state.chat_models.length > 0;
  const card = setupStep(2, "Models", ready && state.embed_installed,
                         "Ready", ready ? "Optional" : "Needs a model");
  if (!state.engine.running) {
    card.appendChild(makeBox("hint", "First the AI engine above."));
    return card;
  }
  const other = state.engine.kind === "openai";
  if (ready) {
    card.appendChild(makeBox("hint", other
      ? state.chat_models.length + " models from " + state.engine.name + "."
      : state.chat_models.length + " chat models installed."));
  } else if (other) {
    card.appendChild(makeBox("hint", state.engine.name + " offers no models yet. Load one there."));
  } else {
    const memory = state.ram_gb ? " for your " + Math.round(state.ram_gb) + " GB of memory" : "";
    card.appendChild(makeBox("hint", "No chat model yet. Suggested" + memory + ": " + state.suggested_model + "."));
    card.appendChild(setupButton("Install " + state.suggested_model, () => installModel(card, state.suggested_model), true));
  }
  if (!state.ollama.running) {
    // Another engine, without Ollama: memories and documents still work,
    // found by matching words instead of by meaning.
    card.appendChild(makeBox("hint",
      "Search by meaning uses Ollama on this computer. Without it, Cerberus finds memories " +
      "and documents by matching words."));
  } else if (!state.embed_installed) {
    card.appendChild(makeBox("hint",
      state.embed_model + " (about 270 MB) lets Cerberus find memories and documents by meaning, " +
      "not only by matching words."));
    card.appendChild(setupButton("Install " + state.embed_model, () => installModel(card, state.embed_model)));
  }
  if (!other) {
    card.appendChild(setupButton("Browse all models", () => {
      setupDialog.close();
      showFeature("models"); // features.js
    }));
  }
  return card;
}

async function installModel(card, name) {
  setupBusy = true;
  for (const button of card.querySelectorAll("button")) button.disabled = true;
  const row = progressRow(card);
  try {
    const last = await streamSteps("/models/pull", { model: name }, row, (step) =>
      step.type === "error" ? step.text : downloadStepText(step)); // models.js
    if (last && last.type === "error") return;
  } catch (error) {
    row.text.textContent = error.message;
    return;
  } finally {
    setupBusy = false;
  }
  await loadModels(); // the chat's model list
  await renderSetup();
}

// ---------- 3. Web search (SearXNG) ----------

const SEARCH_STATUS = {
  ok: "SearXNG answers. Web and Research can search.",
  json_off: "SearXNG runs, but refuses to answer in JSON, which Cerberus needs.",
  offline: "SearXNG doesn't answer at this address. Web and Research won't work until it runs.",
};

function searchStep(state) {
  const search = state.searxng;
  const card = setupStep(3, "Web search (SearXNG)", search.status === "ok", "Ready", "Optional");
  card.appendChild(makeBox("hint", SEARCH_STATUS[search.status]));

  // The address: change it here, it's saved as a setting.
  const form = document.createElement("form");
  form.className = "model-form";
  const address = document.createElement("input");
  address.type = "url";
  address.value = search.url;
  address.setAttribute("aria-label", "SearXNG address");
  form.append(address, setupButton("Save & test", () => form.requestSubmit()));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await fetch("/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ web_url: address.value.trim() }),
    });
    await renderSetup();
  });
  card.appendChild(form);

  if (search.status !== "ok") {
    card.appendChild(setupButton("Help me set up SearXNG", () => searxngHelp(card, search.status)));
  }
  return card;
}

// Writes SearXNG's settings file (never over yours), then shows the
// commands to start it. Starting Docker needs your password, so you run them.
async function searxngHelp(card, status) {
  const response = await fetch("/setup/searxng/prepare", { method: "POST" });
  if (!response.ok) {
    card.appendChild(makeBox("hint", await responseError(response)));
    return;
  }
  const prepared = await response.json();
  card.appendChild(makeBox("hint", prepared.created
    ? "Created " + prepared.path + " with JSON switched on."
    : "Using your existing " + prepared.path + (prepared.json_on ? "." :
      ": add \"- json\" under search: formats: in it, then restart SearXNG.")));
  if (status === "json_off") {
    card.appendChild(commandLine("sudo docker restart searxng"));
  } else {
    card.appendChild(makeBox("hint", "Then run these in a terminal (Docker must be installed), and press Check again:"));
    for (const command of prepared.commands) card.appendChild(commandLine(command));
  }
}

// ---------- Buttons, and opening by itself ----------

document.getElementById("setup-recheck").addEventListener("click", renderSetup);
document.getElementById("setup-done").addEventListener("click", () => setupDialog.close());
document.getElementById("setup-close").addEventListener("click", () => setupDialog.close());
// Closing with Escape while something downloads: keep it open instead.
setupDialog.addEventListener("cancel", (event) => {
  if (setupBusy) event.preventDefault();
});

// When the page opens: if something important is missing (no engine, no
// chat model), the Setup window opens by itself.
fetch("/setup/status")
  .then((response) => response.json())
  .then((state) => {
    if (state.needs_setup) openSetup();
  })
  .catch(() => { /* no answer: the chat shows its own error */ });
