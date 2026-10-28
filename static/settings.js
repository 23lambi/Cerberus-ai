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

// A small heading between groups of cards, like "Helper models".
function sectionTitle(text) {
  const title = document.createElement("h3");
  title.className = "setting-section";
  title.textContent = text;
  settingsFields.appendChild(title);
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
  settingsFields.appendChild(card);
  return card;
}

// ---------- The whole dialog ----------

// Builds every card, filled with the current values.
function fillSettings(values) {
  settingsFields.innerHTML = "";

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
}

// Web search: where SearXNG listens. The Web pill in the chat turns it
// on per message; here is only the address.
function addWebSetting(values) {
  const card = settingCard(
    "Web search",
    "The address of your SearXNG. Only messages sent with Web on go online. " +
      "Cerberus never opens pages on this computer or your home network. " +
      "Offline? Run: sudo docker start searxng"
  );

  const field = document.createElement("input");
  field.type = "url"; // the browser checks it looks like an address
  field.name = "web_url";
  field.className = "setting-input";
  field.value = values.web_url;
  field.placeholder = "http://127.0.0.1:8888";
  card.appendChild(field);
}

// Backup and export: plain links, the server sends the files.
function addBackupCard() {
  const card = settingCard(
    "Backup and export",
    "A ZIP with all chats, memories, settings and files, plus restore steps. " +
      "Keep it private: it holds your data."
  );
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
