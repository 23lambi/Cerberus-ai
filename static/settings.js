// The Settings dialog: one card per setting, in groups. Text settings are
// built from TEXT_SETTINGS, so a new one only needs one entry here (and a
// default in cerberus/settings.py). The on/off features with a model
// (Helper, Eyes) are built from MODEL_FEATURES. At the bottom, the
// built-in prompts can be read (not changed).

const settingsDialog = document.getElementById("settings-dialog");
const settingsForm = document.getElementById("settings-form");
const settingsFields = document.getElementById("settings-fields");
const openSettingsButton = document.getElementById("open-settings");
const resetSettingsButton = document.getElementById("settings-reset");
const cancelSettingsButton = document.getElementById("settings-cancel");
const closeSettingsButton = document.getElementById("settings-close");

// Text settings: the key (as the server calls it), a title and a hint.
const TEXT_SETTINGS = {
  system_prompt: {
    title: "Personality",
    hint:
      "What the model reads first in every chat. Write it like you'd brief a " +
      "person. Cerberus adds memories, documents and project notes after it.",
  },
};

// ---------- Building blocks ----------

// The dialog has a menu on the left and one page on the right. Each
// sectionTitle starts a new page, with its entry in the menu; the cards
// after it go on that page.
let settingsNav = null;
let settingsPages = null;
let settingsPage = null; // the page cards are added to right now
let openPage = "General"; // the page on screen, kept between openings

function sectionTitle(text) {
  const item = document.createElement("button");
  item.type = "button";
  item.className = "settings-nav-item";
  item.textContent = text;
  item.addEventListener("click", () => showSettingsPage(text));
  settingsNav.appendChild(item);

  settingsPage = document.createElement("section");
  settingsPage.className = "settings-page";
  settingsPage.dataset.page = text;
  const heading = document.createElement("h3");
  heading.className = "settings-page-title";
  heading.textContent = text;
  settingsPage.appendChild(heading);
  settingsPages.appendChild(settingsPage);
}

function showSettingsPage(name) {
  if (!settingsPages.querySelector(`[data-page="${name}"]`)) name = "General";
  openPage = name;
  for (const page of settingsPages.children) page.hidden = page.dataset.page !== name;
  for (const item of settingsNav.children) {
    if (item.textContent === name) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  settingsPages.scrollTop = 0;
  growAll(); // a page's text boxes only get a real height once it's shown
}

// One card: a title and a short explanation, and optionally a switch on
// the right. Returns the card, so the caller can add its own fields.
function settingCard(title, hint, aside = null) {
  const card = document.createElement("section");
  card.className = "setting-card";

  const head = document.createElement("div");
  head.className = "setting-head";
  const text = document.createElement("div");
  const heading = document.createElement("h3");
  heading.textContent = title;
  const about = document.createElement("p");
  about.className = "hint";
  about.textContent = hint;
  text.append(heading, about);
  head.appendChild(text);
  if (aside) head.appendChild(aside);

  card.appendChild(head);
  settingsPage.appendChild(card);
  return card;
}

// ---------- The whole dialog ----------

// Builds every card, filled with the current values.
function fillSettings(values) {
  settingsFields.innerHTML = "";
  settingsFields.classList.add("settings-layout");
  settingsNav = document.createElement("nav");
  settingsNav.className = "settings-nav";
  settingsNav.setAttribute("aria-label", "Settings pages");
  settingsPages = document.createElement("div");
  settingsPages.className = "settings-pages";
  settingsPages.tabIndex = -1; // focusable from code only, for scrolling
  settingsFields.append(settingsNav, settingsPages);

  sectionTitle("General");
  const openSetupButton = document.createElement("button");
  openSetupButton.type = "button";
  openSetupButton.textContent = "Open setup";
  openSetupButton.addEventListener("click", () => {
    settingsDialog.close();
    openSetup(); // setup.js
  });
  settingCard(
    "Setup check",
    "Choose where your AI runs and get ready to chat. Optional features can wait.",
    openSetupButton
  );

  addUpdateCard();

  sectionTitle("Assistant");
  // Object.entries turns { a: 1 } into [["a", 1]], so we get key and info.
  for (const [key, info] of Object.entries(TEXT_SETTINGS)) {
    const card = settingCard(info.title, info.hint);

    const textarea = document.createElement("textarea");
    textarea.name = key;
    textarea.className = "prompt-edit";
    textarea.value = values[key];
    textarea.spellcheck = false;

    // "1234 characters, about 309 tokens". A token is about 4 characters
    // of English, so this shows how much of the context window it uses.
    const counter = document.createElement("p");
    counter.className = "hint counter";
    function update() {
      growTextarea(textarea);
      const chars = textarea.value.length;
      counter.textContent = chars + " characters · about " + Math.round(chars / 4) + " tokens";
    }
    textarea.addEventListener("input", update);
    textarea.dataset.grow = "yes"; // openSettings grows it once it's visible
    update();

    card.append(textarea, counter);
  }

  sectionTitle("Helper models");
  for (const feature of MODEL_FEATURES) {
    addModelFeature(values, feature);
  }

  sectionTitle("Web");
  addWebSetting(values);

  sectionTitle("Your data");
  addBackupCard();
  const prompts = settingCard(
    "Built-in prompts",
    "Everything else Cerberus tells the model, read only. Words in {curly braces} " +
      "are filled in by Cerberus. To change them, edit cerberus/prompts.py."
  );
  prompts.appendChild(builtInPrompts());

  sectionTitle("Help");
  addHelpCard();

  showSettingsPage(openPage);
}

// The search engines you can choose (WEB_ENGINES in cerberus/core/config.py).
// key: the setting that holds its API key; link: where to get a key.
const WEB_ENGINES = {
  searxng: {
    name: "SearXNG",
    hint: "Private and free: runs on this computer and asks many engines for you. " +
      "It must be installed; Setup → Web search helps.",
  },
  duckduckgo: {
    name: "DuckDuckGo",
    hint: "Nothing to install, no key. After many searches in a row it may ask " +
      "for a CAPTCHA; then wait a few minutes.",
  },
  brave: {
    name: "Brave Search",
    key: "brave_key",
    link: "https://api-dashboard.search.brave.com/",
    hint: "An official search API, reliable and fast. Needs a free API key.",
  },
  tavily: {
    name: "Tavily",
    key: "tavily_key",
    link: "https://app.tavily.com/",
    hint: "A search API made for AI assistants. Needs a free API key.",
  },
};

// The engine choice and what it needs: SearXNG's address, or a key. Used
// in Settings and in the Setup window. values: web_engine, web_url and
// "<engine>_key_set". Every field has a name, so a form saves it like any
// other setting; an empty key field means "keep the saved key".
function webSearchFields(values) {
  const box = document.createElement("div");
  box.className = "web-fields";

  const engine = document.createElement("select");
  engine.name = "web_engine";
  engine.setAttribute("aria-label", "Search engine");
  for (const [id, info] of Object.entries(WEB_ENGINES)) {
    engine.appendChild(new Option(info.name, id));
  }
  engine.value = values.web_engine;

  const about = makeBox("hint", "");

  const address = document.createElement("input");
  address.type = "url"; // the browser checks it looks like an address
  address.name = "web_url";
  address.className = "setting-input";
  address.value = values.web_url;
  address.placeholder = "http://127.0.0.1:8888";
  address.setAttribute("aria-label", "SearXNG address");

  // SearXNG's address and its on/off switch, shown while SearXNG is chosen.
  const searxngBox = document.createElement("div");
  searxngBox.append(address, searxngSwitch(values));

  // One key field per engine that needs one; only the chosen one is shown.
  const keyRows = {};
  for (const [id, info] of Object.entries(WEB_ENGINES)) {
    if (!info.key) continue;
    const key = document.createElement("input");
    key.type = "password"; // shown as dots, like any password
    key.autocomplete = "off";
    key.name = info.key;
    key.className = "setting-input";
    key.placeholder = values[info.key + "_set"] === "yes"
      ? "A key is saved (type a new one to replace it)" : info.name + " API key";
    key.setAttribute("aria-label", info.name + " API key");

    const link = document.createElement("a");
    link.href = info.link;
    link.target = "_blank"; // opens in your browser, not inside Cerberus
    link.rel = "noopener";
    link.className = "hint";
    link.textContent = "Get a free " + info.name + " key ↗";

    const row = document.createElement("div");
    row.append(key, link);
    keyRows[id] = row;
  }

  function show() {
    about.textContent = WEB_ENGINES[engine.value].hint;
    searxngBox.hidden = engine.value !== "searxng";
    for (const [id, row] of Object.entries(keyRows)) row.hidden = id !== engine.value;
  }
  engine.addEventListener("change", show);
  show();

  box.append(engine, about, searxngBox, ...Object.values(keyRows));
  return box;
}

// SearXNG's switch (cerberus/search/searxng.py). It acts at once, so it
// has no name: the Settings form doesn't save it again. On: SearXNG runs
// while Cerberus is open. Off: it's stopped. When Docker needs sudo,
// Cerberus can't switch it, and shows the command to run instead.
function searxngSwitch(values) {
  const on = document.createElement("input");
  on.type = "checkbox";
  on.className = "switch";
  on.checked = values.searxng_on !== "no";
  on.setAttribute("aria-label", "Run SearXNG");

  const row = document.createElement("div");
  row.className = "searxng-switch";
  const text = document.createElement("div");
  text.append(
    makeBox("searxng-switch-title", "Run SearXNG"),
    makeBox("hint", "On: it runs while Cerberus is open and stops when you close Cerberus. " +
      "Off: it's stopped, and saves your computer's memory.")
  );
  row.append(text, on);

  const note = document.createElement("div");
  note.className = "hint";

  on.addEventListener("change", async () => {
    on.disabled = true;
    note.textContent = on.checked ? "Starting SearXNG…" : "Stopping SearXNG…";
    try {
      const response = await fetch("/setup/searxng/switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ on: on.checked }),
      });
      if (!response.ok) {
        note.textContent = await responseError(response);
        return;
      }
      const answer = await response.json();
      note.textContent = on.checked ? "SearXNG is on." : "SearXNG is off.";
      if (answer.command) {
        note.textContent = "Your SearXNG runs in Docker, which needs your password here, so " +
          "Cerberus can't switch it. Run this in a terminal:";
        note.appendChild(commandLine(answer.command)); // setup.js
      }
    } catch (error) {
      note.textContent = "Could not reach Cerberus: " + error.message;
    } finally {
      on.disabled = false;
    }
  });

  const box = document.createElement("div");
  box.append(row, note);
  return box;
}

// Saves the fields of webSearchFields, then searches once for real, and
// tells you what happened in result. True when the search worked.
async function testWebSearch(fields, result) {
  const values = {};
  for (const field of fields.querySelectorAll("select, input")) {
    if (field.name) values[field.name] = field.value; // not the SearXNG switch
  }
  result.textContent = "Searching…";
  try {
    await fetch("/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    });
    const answer = await (await fetch("/setup/web/test", { method: "POST" })).json();
    // The typed key is saved now: show that, instead of keeping it on screen.
    for (const key of fields.querySelectorAll("input[type=password]")) {
      if (key.value) {
        key.value = "";
        key.placeholder = "A key is saved (type a new one to replace it)";
      }
    }
    result.textContent = answer.ok
      ? "✓ It works: " + answer.count + " results, the first: \"" + answer.first + "\""
      : answer.error;
    return answer.ok;
  } catch (error) {
    result.textContent = "Could not reach Cerberus: " + error.message;
    return false;
  }
}

// Web search: the engine. The Web pill in the chat turns it on per message.
function addWebSetting(values) {
  const card = settingCard(
    "Web search",
    "With Web on, Cerberus searches only when a message needs it (not for " +
      "\"hello\"). With the Helper on, it decides better and turns follow-up " +
      "questions into good search queries. Your search words go to the engine " +
      "you choose. Cerberus never opens pages on this computer or your home network."
  );
  const fields = webSearchFields(values);
  const result = makeBox("hint", "");
  const test = document.createElement("button");
  test.type = "button";
  test.textContent = "Save & test";
  test.addEventListener("click", () => testWebSearch(fields, result));
  card.append(fields, test, result);
}

// Backup and export: plain links, the server sends the files.
function addBackupCard() {
  const card = settingCard(
    "Backup and export",
    "A ZIP with all chats, memories, settings and files, plus restore steps. " +
      "Keep it private: it holds your data."
  );
  // Where your data is: on Windows and macOS it's in a hidden system folder.
  const where = document.createElement("p");
  where.className = "hint";
  card.appendChild(where);
  fetch("/about")
    .then((response) => response.json())
    .then((info) => { where.textContent = "Your data is in: " + info.data_dir; })
    .catch(() => {});

  const links = document.createElement("div");
  links.className = "setting-links";

  const backup = document.createElement("a");
  backup.className = "button-link";
  backup.href = "/backup";
  backup.textContent = "Download full backup (.zip)";
  links.appendChild(backup);

  // The current chat only when one is open.
  if (currentChatId) {
    for (const [format, label] of [["markdown", "Markdown"], ["json", "JSON"]]) {
      const link = document.createElement("a");
      link.className = "button-link";
      link.href = "/chats/" + currentChatId + "/export?format=" + format;
      link.textContent = "Export this chat (" + label + ")";
      links.appendChild(link);
    }
  }
  card.appendChild(links);
}

// ---------- Updates ----------

// The installed app updates itself here; the launcher only installs it
// once. Run from source, git pull updates Cerberus instead.
let updateInfo = null;

async function updateRequest(path, method = "POST") {
  const response = await fetch(path, { method });
  if (!response.ok) throw new Error(await responseError(response)); // app.js
  updateInfo = await response.json();
  openSettingsButton.classList.toggle("has-update", ["available", "ready"].includes(updateInfo.state));
  return updateInfo;
}

// A quiet check soon after start: a dot on Settings when a version waits.
setTimeout(async () => {
  try {
    if ((await updateRequest("/updates", "GET")).managed) await updateRequest("/updates/check");
  } catch (_) { /* offline: Settings can check again */ }
}, 4000);

function megabytes(bytes) {
  return Math.round(bytes / 1024 / 1024) + " MB";
}

function addUpdateCard() {
  const card = settingCard(
    "Cerberus version",
    "New versions come from GitHub. Updating keeps your chats, settings and models."
  );
  const line = document.createElement("p");
  line.className = "hint";
  // What's new: the release notes' "What's new" part, from GitHub.
  const notes = document.createElement("details");
  notes.className = "update-notes";
  notes.open = true;
  const notesTitle = document.createElement("summary");
  const notesBody = document.createElement("div");
  notes.append(notesTitle, notesBody);
  const actions = document.createElement("div");
  actions.className = "setting-links";
  const action = document.createElement("button");
  action.type = "button";
  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "Uninstall Cerberus…";
  actions.append(action, remove);
  card.append(line, notes, actions);

  function show(info, problem = "") {
    const current = "version " + info.current;
    remove.hidden = !info.managed;
    action.hidden = !info.managed;
    // Only for a version you don't have yet. The notes are Markdown from the
    // release page: DOMPurify cleans them like every model answer.
    notes.hidden = !(info.managed && info.notes && ["available", "downloading", "ready"].includes(info.state));
    if (!notes.hidden) {
      notesTitle.textContent = "What's new in " + info.latest;
      notesBody.innerHTML = DOMPurify.sanitize(marked.parse(info.notes));
    }
    action.disabled = false;
    if (!info.managed) {
      line.textContent = "You're running Cerberus from source. Update it with git pull.";
      return;
    }
    const states = {
      idle: ["You have " + current + ".", "Check for updates", check],
      current: ["You have " + current + ". It's the latest.", "Check again", check],
      available: [info.latest + " is available (" + megabytes(info.total) + "). You have " + current + ".",
        "Download update", download],
      downloading: ["Downloading " + info.latest + "… " + Math.round((info.done / (info.total || 1)) * 100) + "%",
        "Downloading…", null],
      ready: [info.latest + " is ready. Restart Cerberus to finish updating.", "Restart now", restart],
      error: [info.message || "The update failed.", "Try again", check],
    };
    const [text, label, handler] = states[info.state] || states.idle;
    line.textContent = problem || text;
    action.textContent = label;
    action.disabled = !handler;
    action.onclick = handler;
    if (info.state === "downloading" && card.isConnected) {
      setTimeout(() => updateRequest("/updates", "GET").then(show).catch(() => {}), 500);
    }
  }

  async function run(path, busyText) {
    action.disabled = true;
    line.textContent = busyText;
    try {
      show(await updateRequest(path));
    } catch (error) {
      show(updateInfo || { managed: true, current: "", state: "idle" }, error.message);
    }
  }
  function check() { run("/updates/check", "Checking for updates…"); }
  function download() { run("/updates/download", "Starting the download…"); }
  async function restart() {
    action.disabled = true;
    line.textContent = "Restarting Cerberus…";
    try {
      await updateRequest("/updates/restart");
    } catch (error) {
      show(updateInfo, error.message);
    }
  }
  remove.addEventListener("click", async () => {
    if (!confirm("Uninstall Cerberus? The app closes and is removed. Your chats, settings and models are kept.")) return;
    remove.disabled = true;
    try {
      await updateRequest("/updates/uninstall");
      line.textContent = "Closing Cerberus…";
    } catch (error) {
      line.textContent = error.message;
      remove.disabled = false;
    }
  });

  line.textContent = "Checking your version…";
  (updateInfo ? Promise.resolve(updateInfo) : updateRequest("/updates", "GET"))
    .then((info) => show(info))
    .catch(() => { line.textContent = "Version information is unavailable."; });
}

// ---------- Help ----------

// Copy diagnostics: version, system, engine and the end of the log, for a bug
// report. It's shown before it's copied, so you see exactly what you share.
function addHelpCard() {
  const card = settingCard(
    "Report a problem",
    "Copy the diagnostics into your bug report. They hold no chats or API keys, " +
      "and your home folder shows as ~. Read them first if you like."
  );
  const details = document.createElement("details");
  details.className = "built-in";
  const summary = document.createElement("summary");
  summary.textContent = "Show diagnostics";
  const text = document.createElement("pre");
  text.className = "diagnostics";
  details.append(summary, text);

  const status = document.createElement("p");
  status.className = "hint";
  const links = document.createElement("div");
  links.className = "setting-links";
  const copy = document.createElement("button");
  copy.type = "button";
  copy.textContent = "Copy diagnostics";
  const report = document.createElement("a");
  report.className = "button-link";
  report.href = "https://github.com/23lambi/Cerberus-ai/issues/new/choose";
  report.target = "_blank"; // opens in your browser, not inside Cerberus
  report.textContent = "Report a problem on GitHub";
  links.append(copy, report);
  card.append(details, links, status);

  async function load() {
    const response = await fetch("/diagnostics?model=" + encodeURIComponent(modelSelect.value)); // app.js
    if (!response.ok) throw new Error(await responseError(response));
    text.textContent = await response.text();
    return text.textContent;
  }
  details.addEventListener("toggle", () => {
    if (details.open && !text.textContent) load().catch((error) => { text.textContent = error.message; });
  });
  copy.addEventListener("click", async () => {
    copy.disabled = true;
    status.textContent = "Collecting…";
    try {
      const diagnostics = await load();
      details.open = true;
      status.textContent = (await copyShown(text, diagnostics))
        ? "Copied. Paste it into your bug report."
        : "Selected. Press Ctrl+C (⌘C on a Mac) to copy it.";
    } catch (error) {
      status.textContent = "Could not collect diagnostics: " + error.message;
    } finally {
      copy.disabled = false;
    }
  });
}

// Copies text that is shown in element; true when it worked. Selecting and
// copying needs no permission. The newer clipboard API may ask for one, and
// some desktop windows never answer, so it only gets two seconds.
async function copyShown(element, text) {
  const range = document.createRange();
  range.selectNodeContents(element);
  getSelection().removeAllRanges();
  getSelection().addRange(range); // stays selected for Ctrl+C if copying fails
  try {
    if (document.execCommand("copy")) return true;
  } catch (_) { /* not supported: try the clipboard API */ }
  try {
    await Promise.race([
      navigator.clipboard.writeText(text),
      new Promise((_, reject) => setTimeout(() => reject(new Error("no answer")), 2000)),
    ]);
    return true;
  } catch (_) {
    return false;
  }
}

// Makes a textarea exactly as tall as its text, so you see all of it
// without scrolling inside a small box. (CSS caps it at max-height.)
function growTextarea(textarea) {
  textarea.style.height = "auto";
  textarea.style.height = textarea.scrollHeight + 2 + "px"; // + the border
}

// ---------- The built-in prompts (read only) ----------

// A folded section. The prompts are only loaded the first time it's
// opened: most visits to Settings don't need them.
function builtInPrompts() {
  const details = document.createElement("details");
  details.className = "built-in";

  const summary = document.createElement("summary");
  summary.textContent = "Show the prompts";

  const list = document.createElement("div");
  details.append(summary, list);

  // "toggle" fires when a <details> opens or closes.
  details.addEventListener("toggle", async () => {
    if (!details.open || list.children.length > 0) return;
    const response = await fetch("/settings/prompts");
    const data = await response.json();
    for (const prompt of data.prompts) {
      const title = document.createElement("h4");
      title.textContent = prompt.name;
      const about = document.createElement("p");
      about.className = "hint";
      about.textContent = prompt.about;
      // A <pre> keeps the prompt's own line breaks, like in prompts.py.
      const text = document.createElement("pre");
      text.className = "prompt-text";
      text.textContent = prompt.text;
      list.append(title, about, text);
    }
  });
  return details;
}

// ---------- Features with their own model ----------

// The on/off features that use a second model. Each one is saved as two
// settings, "<key>_on" and "<key>_model" (see cerberus/settings.py), and
// gets the same kind of card. A new feature = one more object in this list.
const MODEL_FEATURES = [
  {
    key: "helper",
    title: "Helper",
    // Any chat model can be the Helper. filter(Boolean) drops the "None"
    // choice of the chat dropdown, whose value is "" (and "" counts as false).
    models: () => [...modelSelect.options].map((option) => option.value).filter(Boolean),
    hint:
      "A small, fast model for the jobs in the background: sorting messages, " +
      "chat titles, summaries and project notes. Your chat model then only has " +
      "to answer. Try llama3.2:3b. Off: the chat model does everything.",
  },
  {
    key: "eyes",
    title: "Eyes",
    // Only models that can see. visionModels comes from app.js.
    models: () => [...visionModels],
    hint:
      "A vision model that describes your images for chat models that can't " +
      "see. Try gemma3:4b. Models that can see get the images themselves.",
  },
];

// One card: its switch on the right, and the model it uses below.
function addModelFeature(values, feature) {
  // The switch: a checkbox that style.css draws as a sliding knob.
  // Settings are saved as text, so it becomes "yes" or "no".
  const on = document.createElement("input");
  on.type = "checkbox";
  on.className = "switch";
  on.name = feature.key + "_on";
  on.checked = values[on.name] === "yes";
  on.setAttribute("aria-label", "Use " + feature.title);

  const card = settingCard(feature.title, feature.hint, on);

  const select = document.createElement("select");
  select.name = feature.key + "_model";
  const models = feature.models();
  select.appendChild(new Option(models.length ? "Pick a model…" : "No fitting models installed", ""));
  for (const name of models) {
    select.appendChild(new Option(name, name));
  }
  select.value = values[select.name];
  // A model that was removed isn't in the list anymore.
  if (select.value !== values[select.name]) select.value = "";

  // The dropdown only matters while the feature is on.
  select.disabled = !on.checked;
  on.addEventListener("change", () => {
    select.disabled = !on.checked;
  });
  card.appendChild(select);
}

async function openSettings() {
  const response = await fetch("/settings");
  const values = await response.json();
  fillSettings(values);
  settingsDialog.showModal(); // a modal dialog blocks the page behind it
  growAll(); // only now the boxes are visible and have a real height
  // Start in the page, not on the close button: the arrow keys scroll it.
  settingsPages.focus();
}

function growAll() {
  for (const textarea of settingsFields.querySelectorAll("textarea[data-grow]")) {
    growTextarea(textarea);
  }
}

settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  // Collect { key: value } from every field. Textareas and selects both
  // have .name and .value; a checkbox has .checked, saved as "yes"/"no".
  const values = {};
  for (const field of settingsFields.querySelectorAll("textarea, select, input")) {
    if (!field.name) continue; // like SearXNG's switch: it saves itself
    values[field.name] = field.type === "checkbox" ? (field.checked ? "yes" : "no") : field.value;
  }

  await fetch("/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(values),
  });

  settingsDialog.close();
  loadEyes(); // Eyes on or off changes which models may get images
  freeOtherModels(); // a feature that was switched off frees its model's RAM
});

resetSettingsButton.addEventListener("click", async () => {
  if (!confirm("Reset all settings to the defaults?")) return;

  // The server answers with the default values; show them in the fields.
  const response = await fetch("/settings/reset", { method: "POST" });
  const values = await response.json();
  fillSettings(values);
  growAll();
});

cancelSettingsButton.addEventListener("click", () => settingsDialog.close());
closeSettingsButton.addEventListener("click", () => settingsDialog.close());
openSettingsButton.addEventListener("click", openSettings);
