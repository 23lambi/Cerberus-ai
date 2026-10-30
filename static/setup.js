// The Setup window: is everything Cerberus needs ready, and if not, fix it
// from here, one step at a time: choose where AI runs, get a model, then say
// hi to check that it all works. The pixel mascot guides you through it.
// The server checks (cerberus/core/setup.py); this file shows the result and
// the buttons that make sense for it.

const setupDialog = document.getElementById("setup-dialog");
const setupBody = document.getElementById("setup-body");
const setupBack = document.getElementById("setup-back");
const setupNext = document.getElementById("setup-next");
let setupBusy = false; // a download is running: don't redraw over it
let setupState = null; // the last answer from /setup/status
let setupStepIndex = null; // the step on screen; null = the first unfinished one

const SETUP_STEPS = ["Choose your AI", "Get a model", "Say hi"];

async function openSetup() {
  if (!setupDialog.open) setupDialog.showModal();
  setupStepIndex = null;
  await renderSetup();
}

// Which steps are done. "Say hi" is always open: it's the check itself.
function setupDone(state) {
  return [state.engine.running, state.chat_models.length > 0, false];
}

// Asks the server what's ready, then draws the step on screen.
async function renderSetup() {
  if (setupBusy) return;
  setupBody.innerHTML = "";
  setupBody.appendChild(makeBox("hint", "Checking…"));
  try {
    // Both at the same time: what's ready, and the engines to choose from.
    const [statusResponse, enginesResponse] = await Promise.all([fetch("/setup/status"), fetch("/setup/engines")]);
    if (!statusResponse.ok) throw new Error(await responseError(statusResponse));
    if (!enginesResponse.ok) throw new Error(await responseError(enginesResponse));
    setupState = await statusResponse.json();
    setupState.engines = await enginesResponse.json();
  } catch (error) {
    setupBody.innerHTML = "";
    setupBody.appendChild(makeBox("hint", "Could not reach Cerberus: " + error.message));
    return;
  }
  const done = setupDone(setupState);
  if (setupStepIndex === null) setupStepIndex = done.indexOf(false);
  // A later step needs the earlier ones: never show it before they're done.
  setupStepIndex = Math.min(setupStepIndex, done.indexOf(false));
  drawSetupStep();
}

function drawSetupStep() {
  const state = setupState;
  const done = setupDone(state);
  const step = setupStepIndex;
  setupBody.innerHTML = "";
  setupBody.append(setupProgress(done, step), setupGuide(state, step));
  if (step === 0) setupBody.appendChild(engineStep(state));
  if (step === 1) setupBody.appendChild(modelsStep(state));
  if (step === 2) {
    setupBody.appendChild(helloStep(state));
    const optional = setupDisclosure("Optional · Web search", webReady(state.web) ? state.web.name : "Set up later");
    optional.body.appendChild(searchStep(state));
    setupBody.appendChild(optional.root);
  }
  setupBack.hidden = step === 0;
  setupNext.textContent = step === SETUP_STEPS.length - 1 ? "Start chatting" : "Next";
  setupNext.disabled = step < SETUP_STEPS.length - 1 && !done[step];
}

// The row of steps on top: done ones get a ✓, the current one stands out.
function setupProgress(done, current) {
  const list = document.createElement("ol");
  list.className = "setup-progress";
  SETUP_STEPS.forEach((name, index) => {
    const item = document.createElement("li");
    if (index === current) item.className = "current";
    else if (done[index]) item.className = "done";
    item.textContent = (done[index] && index !== current ? "✓ " : index + 1 + " ") + name;
    list.appendChild(item);
  });
  return list;
}

// The mascot and one sentence about the step: happy when it's done, sad when
// something is missing. Its picture changes while the hello streams in.
function setupGuide(state, step) {
  const guide = document.createElement("div");
  guide.className = "setup-guide";
  const mascot = document.createElement("img");
  mascot.id = "setup-mascot";
  mascot.alt = "";
  const engine = state.engine.name || "Ollama";
  const lines = [
    state.engine.running
      ? ["mascot-idle", "Connected to " + engine + ". Next, a model to chat with."]
      : ["mascot-sad", "Let's connect your AI. Ollama is the easiest: it runs on this computer, privately."],
    state.chat_models.length
      ? ["mascot-idle", state.chat_models.length + " chat models ready. One last step."]
      : ["mascot-idle", "Now a model: the brain Cerberus talks with. We'll suggest one that fits your computer."],
    ["mascot-idle", "Say hi to check that everything works."],
  ];
  const [picture, text] = lines[step];
  mascot.src = "/static/" + picture + ".svg";
  guide.append(mascot, makeBox("setup-guide-text", text));
  return guide;
}

function setMascot(picture) {
  const mascot = document.getElementById("setup-mascot");
  if (mascot) mascot.src = "/static/" + picture + ".svg";
}

// ---------- 3. Say hi ----------

// A first real answer from the chosen model, streamed in. Nothing is saved.
function helloStep(state) {
  const card = setupStep(3, "Say hi", false, "", "Last step");
  card.querySelector(".setup-badge").hidden = true;
  const model = modelSelect.value || state.chat_models[0]; // app.js
  card.appendChild(makeBox("hint", "Cerberus sends a short first message to " + model + "."));
  const answer = makeBox("setup-hello", "");
  answer.hidden = true;
  const send = setupButton("Say hi", async () => {
    setupBusy = true;
    send.disabled = true;
    answer.hidden = false;
    answer.textContent = "";
    answer.classList.remove("error");
    setMascot("mascot-thinking");
    let failure = "";
    try {
      const response = await fetch("/setup/hello", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      await readEvents(response, (event) => { // app.js
        if (event.error) failure = event.error;
        if (event.text) {
          setMascot("mascot-talking");
          answer.textContent += event.text;
        }
      });
      if (failure) throw new Error(failure);
      if (!answer.textContent.trim()) throw new Error("The model answered with nothing. Try another model.");
      setMascot("mascot");
      send.textContent = "Say hi again";
      document.querySelector(".setup-guide-text").textContent = "It works! You're ready to chat.";
    } catch (error) {
      setMascot("mascot-sad");
      answer.classList.add("error");
      answer.textContent = error.message;
    } finally {
      setupBusy = false;
      send.disabled = false;
    }
  }, true);
  card.append(send, answer);
  return card;
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
  heading.textContent = number ? number + ". " + title : title;
  head.append(heading, badge);
  card.appendChild(head);
  return card;
}

// Native disclosures keep technical and optional settings keyboard accessible.
function setupDisclosure(title, note = "") {
  const root = document.createElement("details");
  root.className = "setup-disclosure";
  const summary = document.createElement("summary");
  const label = document.createElement("span");
  label.textContent = title;
  summary.appendChild(label);
  if (note) summary.appendChild(makeBox("setup-summary-note", note));
  const body = document.createElement("div");
  body.className = "setup-disclosure-body";
  root.append(summary, body);
  return { root, body };
}

function setupField(label, input) {
  const wrapper = document.createElement("label");
  wrapper.className = "setup-field";
  wrapper.append(makeBox("setup-field-label", label), input);
  return wrapper;
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
    // settings.js: copies without asking for clipboard permission first.
    copy.textContent = (await copyShown(code, command)) ? "Copied!" : "Press Ctrl+C";
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
  const card = setupStep(1, "Choose your AI", state.engine.running, "Connected", "Choose below");
  const engines = state.engines;
  const groups = {
    local: { title: "On this computer", hint: "Keep conversations local", presets: ["ollama", "llamacpp", "lmstudio", "jan"] },
    cloud: { title: "Cloud service", hint: "Connect with an API key", presets: ["huggingface", "openai", "groq", "openrouter"] },
  };
  let preset = engines.engine === "ollama" ? "ollama" : engines.openai.preset;
  let group = Object.keys(groups).find((key) => groups[key].presets.includes(preset)) || "custom";
  const choices = document.createElement("div");
  choices.className = "setup-choices";
  choices.setAttribute("role", "group");
  choices.setAttribute("aria-label", "Where your AI runs");
  const buttons = {};
  const selection = document.createElement("div");
  selection.className = "setup-engine";
  const draw = () => {
    selection.innerHTML = "";
    for (const key of Object.keys(buttons)) buttons[key].setAttribute("aria-pressed", String(group === key));
    custom.setAttribute("aria-pressed", String(group === "custom"));
    const details = document.createElement("div");
    details.className = "setup-engine";
    if (group !== "custom") {
      const choose = document.createElement("select");
      choose.setAttribute("aria-label", "AI engine");
      for (const key of groups[group].presets) {
        choose.appendChild(new Option(key === "ollama" ? "Ollama · easiest to set up" : engines.presets[key].name, key));
      }
      choose.value = preset;
      selection.appendChild(setupField(group === "local" ? "Local app" : "Provider", choose));
      choose.addEventListener("change", () => { preset = choose.value; draw(); });
    }
    if (preset === "ollama") ollamaDetails(details, state, engines.engine === "ollama");
    else otherEngineDetails(details, state, engines, preset);
    selection.appendChild(details);
  };
  for (const [key, info] of Object.entries(groups)) {
    const button = setupButton("", () => {
      group = key;
      const current = engines.engine === "ollama" ? "ollama" : engines.openai.preset;
      preset = info.presets.includes(current) ? current : info.presets[0];
      draw();
    });
    button.className = "setup-choice";
    const title = document.createElement("strong");
    title.textContent = info.title;
    button.append(title, makeBox("hint", info.hint));
    choices.appendChild(button);
    buttons[key] = button;
  }
  const custom = setupButton("Custom connection", () => { group = "custom"; preset = "custom"; draw(); });
  custom.className = "setup-custom";
  card.append(choices, custom, selection);
  draw();
  return card;
}

// Saves the engine choice and tests it; then everything updates.
async function useEngine(body, details) {
  const progress = makeBox("hint", "Connecting…");
  progress.setAttribute("role", "status");
  details.appendChild(progress);
  const buttons = [...details.querySelectorAll("button")];
  for (const button of buttons) button.disabled = true;
  try {
    const response = await fetch("/setup/engine", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const result = response.ok ? await response.json() : { ok: false, error: await responseError(response) };
    if (!result.ok) throw new Error(result.error);
    await afterEngineChange();
  } catch (error) {
    progress.textContent = error.message;
    progress.setAttribute("role", "alert");
  } finally {
    for (const button of buttons) button.disabled = false;
  }
}

// An OpenAI-compatible engine: address, key, help, and the cloud warning.
function otherEngineDetails(details, state, engines, preset, connectionOnly = false) {
  if (preset === "llamacpp" && !connectionOnly) {
    managedLlamaDetails(details, engines.llamacpp);
    const external = setupDisclosure("Connect to an existing server instead");
    otherEngineDetails(external.body, state, engines, preset, true);
    details.appendChild(external.root);
    return;
  }
  const info = engines.presets[preset];
  const chosen = engines.engine === "openai" && engines.openai.preset === preset;
  if (chosen) {
    details.appendChild(makeBox("hint", state.engine.running
      ? "✓ Connected to " + state.engine.name + ": " + state.engine.models.length + " models."
      : state.engine.error));
  }
  if (preset !== "llamacpp") details.appendChild(makeBox("hint", info.key_help));

  const address = document.createElement("input");
  address.type = "url";
  address.placeholder = "Address, like http://127.0.0.1:1234/v1";
  address.value = chosen ? engines.openai.url : info.url;
  if (!chosen && preset === "llamacpp" && engines.llamacpp.enabled) {
    address.value = "http://127.0.0.1:" + engines.llamacpp.port + "/v1";
  }
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

  const advanced = setupDisclosure("Connection settings");
  advanced.body.append(setupField("Server address", address));
  if (info.key) {
    details.appendChild(setupField(chosen && engines.openai.key_set ? "API key · saved" : "API key", key));
  } else {
    advanced.body.appendChild(setupField("API key · only if required", key));
  }
  if (preset === "custom" || connectionOnly) advanced.root.open = true;
  details.append(advanced.root, warning, setupButton(chosen ? "Save & connect" : "Connect", () =>
    useEngine({ engine: "openai", preset, url: address.value.trim(), key: key.value.trim() }, details), true));
}

function managedLlamaDetails(details, config) {
  details.appendChild(makeBox("hint", config.owned
    ? "llama.cpp is running. Cerberus will stop it when you close the app."
    : "Choose a downloaded GGUF model. Cerberus will start it for you and remember it next time."));
  const advanced = setupDisclosure("Advanced", "Executable & port");
  const field = (parent, label, value, type = "text") => {
    const input = document.createElement("input");
    input.type = type;
    input.value = value;
    input.placeholder = label;
    input.setAttribute("aria-label", label);
    parent.appendChild(setupField(label, input));
    return input;
  };
  const model = field(details, "Model file · full path to a .gguf file", config.model);
  const binary = field(advanced.body, "llama-server executable or path", config.binary);
  const port = field(advanced.body, "Local server port", config.port, "number");
  details.appendChild(advanced.root);
  port.min = "1";
  port.max = "65535";
  const run = async (action, body) => {
    setupBusy = true;
    for (const button of details.querySelectorAll("button")) button.disabled = true;
    const progress = makeBox("hint", action === "start" ? "Loading GGUF model…" : "Stopping llama.cpp…");
    details.appendChild(progress);
    try {
      const response = await fetch("/setup/llamacpp/" + action, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!response.ok) throw new Error(await responseError(response));
      setupBusy = false;
      await afterEngineChange();
    } catch (error) {
      progress.textContent = error.message;
    } finally {
      setupBusy = false;
      for (const button of details.querySelectorAll("button")) button.disabled = false;
    }
  };
  if (config.owned) {
    model.disabled = binary.disabled = port.disabled = true;
    details.appendChild(makeBox("hint", "To change the model, stop it first."));
  } else {
    details.appendChild(makeBox("hint", "Requires llama-server. First start can take up to two minutes."));
    details.appendChild(setupButton("Start with Cerberus", () => run("start", {
      binary: binary.value.trim(), model: model.value.trim(), port: Number(port.value),
    }), true));
  }
  if (config.owned || config.enabled) details.appendChild(setupButton("Stop & disable automatic start", () => run("stop")));
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
    card.appendChild(makeBox("hint", "Connected to Ollama. Your conversations stay on this computer."));
    return;
  }
  if (engine.managed) {
    card.appendChild(makeBox("hint", "Ollama is ready to start."));
    card.appendChild(setupButton("Start Ollama", () => startOllama(card), true));
  } else if (engine.system) {
    // A system Ollama: started by its own service, not by Cerberus (else
    // it would look for your models in another folder).
    card.appendChild(makeBox("hint", "Ollama is installed but not running. Start it, then press Check again:"));
    card.appendChild(commandLine(engine.start_hint));
  } else if (engine.can_download) {
    card.appendChild(makeBox("hint",
      "Download Ollama once to run AI on this computer. About 1.5 GB (220 MB on Mac). " +
      "Cerberus handles installation and startup."));
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
  const card = setupStep(2, "Your chat model", ready, "Ready", "Next step");
  if (!state.engine.running) {
    card.appendChild(makeBox("hint", "Connect your AI above, then we’ll help you choose a model."));
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
    card.appendChild(makeBox("hint", "Recommended" + memory + ": " + state.suggested_model + ". Download it once to start chatting."));
    card.appendChild(setupButton("Download recommended model", () => installModel(card, state.suggested_model), true));
  }
  if (!state.embed_installed) {
    const extra = setupDisclosure("Better document search", "Optional");
    if (!state.ollama.running) {
      extra.body.appendChild(makeBox("hint",
        "Your documents are searchable by keywords. Set up Ollama to also search by meaning."));
    } else {
      extra.body.appendChild(makeBox("hint",
        "Find documents by meaning as well as keywords. This optional download is about 270 MB."));
      extra.body.appendChild(setupButton("Enable better search", () => installModel(extra.body, state.embed_model)));
    }
    card.appendChild(extra.root);
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

// ---------- 3. Web search ----------

// What the status from /setup/status means ({name} = the chosen engine).
const SEARCH_STATUS = {
  ok: "{name} answers. Web and Research can search.",
  ready: "{name} is chosen. Press Save & test to try a search.",
  no_key: "{name} needs an API key.",
  off: "SearXNG is switched off. Switch it on below, or choose another engine.",
  json_off: "SearXNG runs, but refuses to answer in JSON, which Cerberus needs.",
  offline: "SearXNG isn't reachable. Set it up below, or choose an engine that needs nothing installed.",
};
// The last Save & test answer, kept while the window redraws itself.
let webTestResult = "";

function webReady(search) {
  return search.status === "ok" || search.status === "ready";
}

function searchStep(state) {
  const search = state.web;
  const card = setupStep(null, "Search the web", webReady(search), "Ready", "Optional");
  card.appendChild(makeBox("hint", "Add web sources to answers and use Research. You can chat without this."));
  card.appendChild(makeBox("hint", SEARCH_STATUS[search.status].replace("{name}", search.name)));

  // The same fields as in Settings (settings.js).
  const fields = webSearchFields(search);
  const result = makeBox("hint", webTestResult);
  // Another engine chosen: the old answer was about the old one.
  fields.querySelector("select").addEventListener("change", () => (result.textContent = webTestResult = ""));
  const test = setupButton("Save & test", async () => {
    test.disabled = true;
    await testWebSearch(fields, result);
    webTestResult = result.textContent;
    await renderSetup(); // the status and the ✓ follow the saved engine
  }, true);
  card.append(fields, test, result);

  // How to get SearXNG: only while SearXNG is chosen in the list.
  const panel = searxngPanel(search);
  const engine = fields.querySelector("select");
  const showPanel = () => (panel.hidden = engine.value !== "searxng");
  engine.addEventListener("change", showPanel);
  showPanel();
  card.appendChild(panel);
  return card;
}

// SearXNG: start or remove Cerberus's own copy, or choose how to get one:
// Cerberus installs it with Python, or you run it with Docker.
function searxngPanel(search) {
  const panel = document.createElement("div");
  panel.className = "searxng-panel";
  const working = search.web_engine === "searxng" && search.status === "ok";
  const off = search.web_engine === "searxng" && search.status === "off"; // the switch decides

  if (search.searxng_installed) {
    if (!working && !off) {
      panel.append(
        makeBox("hint", "Cerberus's SearXNG is installed, but not running."),
        setupButton("Start SearXNG", () => startSearxng(panel), true)
      );
    }
    const more = setupDisclosure("Cerberus's SearXNG", "Installed");
    more.body.append(
      makeBox("hint", "It starts and stops together with Cerberus, and only this computer can reach it."),
      setupButton("Remove it", () => removeSearxng(panel))
    );
    panel.appendChild(more.root);
    return panel;
  }
  if (working || off) return panel; // it answers, or you switched it off

  panel.appendChild(makeBox("hint", "Don't have SearXNG yet? Choose how to get it:"));

  const install = setupButton("Install it for me", () => installSearxng(panel), true);
  panel.append(install, makeBox("hint",
    "No Docker needed. Cerberus downloads SearXNG (about 180 MB) into its own folder " +
    "and runs it in the background, only for this computer. Takes a minute or two."));
  if (search.searxng_windows) {
    panel.appendChild(makeBox("hint",
      "On Windows, SearXNG isn't officially supported: installing may work, " +
      "but Docker or DuckDuckGo are the surer choice."));
  }
  if (search.searxng_problem) {
    install.disabled = true;
    panel.appendChild(makeBox("hint", search.searxng_problem));
  }

  panel.append(
    setupButton("Use Docker instead", () => searxngHelp(panel, search)),
    makeBox("hint", "If you already use Docker: shows the commands to run.")
  );
  return panel;
}

// Installs SearXNG (cerberus/search/searxng.py) and starts it. The steps
// stream in like the Ollama download; closing the window cancels.
async function installSearxng(panel) {
  setupBusy = true;
  for (const button of panel.querySelectorAll("button")) button.disabled = true;
  const row = progressRow(panel);
  const STEPS = {
    download: "Downloading SearXNG…",
    venv: "Making its own Python environment…",
    packages: "Installing its packages… (a minute or two)",
    done: "Installed.",
    starting: "Starting SearXNG…",
    running: "SearXNG is running.",
  };
  try {
    const last = await streamSteps("/setup/searxng/install", null, row,
      (step) => (step.step === "error" ? step.text : STEPS[step.step] || ""));
    if (last && last.step === "error") return; // the text already says why
  } catch (error) {
    row.text.textContent = error.message;
    return;
  } finally {
    setupBusy = false;
  }
  webTestResult = "";
  await renderSetup();
}

async function startSearxng(panel) {
  const row = progressRow(panel);
  row.text.textContent = "Starting SearXNG…";
  const response = await fetch("/setup/searxng/start", { method: "POST" });
  if (!response.ok) {
    row.text.textContent = await responseError(response);
    return;
  }
  webTestResult = "";
  await renderSetup();
}

async function removeSearxng(panel) {
  if (!confirm("Remove Cerberus's SearXNG from this computer? You can install it again later.")) return;
  for (const button of panel.querySelectorAll("button")) button.disabled = true;
  await fetch("/setup/searxng/remove", { method: "POST" });
  await renderSetup();
}

// Writes SearXNG's settings file (never over yours), then shows the
// commands to start it. On Linux Docker needs your password, so you run them.
async function searxngHelp(card, search) {
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
  if (search.status === "json_off") {
    card.appendChild(commandLine(search.restart_command));
  } else {
    card.appendChild(makeBox("hint", "Then run these in a terminal (Docker must be installed), and press Check again:"));
    for (const command of prepared.commands) card.appendChild(commandLine(command));
  }
}

// ---------- Buttons, and opening by itself ----------

document.getElementById("setup-recheck").addEventListener("click", renderSetup);
document.getElementById("setup-done").addEventListener("click", () => setupDialog.close());
setupBack.addEventListener("click", () => {
  if (setupBusy) return;
  setupStepIndex = Math.max(0, setupStepIndex - 1);
  drawSetupStep();
});
setupNext.addEventListener("click", () => {
  if (setupBusy) return;
  if (setupStepIndex === SETUP_STEPS.length - 1) {
    setupDialog.close();
    return;
  }
  setupStepIndex += 1;
  drawSetupStep();
});
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
