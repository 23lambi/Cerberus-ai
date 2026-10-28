// The Settings dialog. Text settings are built from TEXT_SETTINGS, so a
// new one only needs one entry here (and a default in cerberus/settings.py).
// The on/off features with a model (Helper, Eyes) are built from MODEL_FEATURES.
// At the bottom, the built-in prompts can be read (not changed).

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
      "The system prompt: the first thing the model reads in every chat, before " +
      "your messages. Write it like instructions to a person. Memories, " +
      "documents and project notes are added after it by Cerberus.",
  },
};

// Builds one section per setting, filled with the current values.
function fillSettings(values) {
  settingsFields.innerHTML = "";

  // Object.entries turns { a: 1 } into [["a", 1]], so we get key and info.
  for (const [key, info] of Object.entries(TEXT_SETTINGS)) {
    const section = document.createElement("fieldset");
    section.className = "setting-group";

    const legend = document.createElement("legend");
    legend.textContent = info.title;

    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = info.hint;

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
      counter.textContent = chars + " characters, about " + Math.round(chars / 4) + " tokens";
    }
    textarea.addEventListener("input", update);
    textarea.dataset.grow = "yes"; // openSettings grows it once it's visible
    update();

    section.append(legend, hint, textarea, counter);
    settingsFields.appendChild(section);
  }

  for (const feature of MODEL_FEATURES) {
    addModelFeature(values, feature);
  }
  addWebSetting(values);
  settingsFields.appendChild(builtInPrompts());
  const downloads = document.createElement("fieldset");
  downloads.className = "setting-group";
  const legend = document.createElement("legend");
  legend.textContent = "Backup and export";
  const note = document.createElement("p");
  note.className = "hint";
  note.textContent = "Download all chats, memories, settings and original documents. The ZIP includes restore instructions. Personal memories are shared across projects; documents and past-chat search stay within their project. Existing documents belong to All chats.";
  const backup = document.createElement("a");
  backup.href = "/backup";
  backup.textContent = "Download full backup (.zip)";
  downloads.append(legend, note, backup);
  if (currentChatId) {
    for (const [format, label] of [["markdown", "Markdown"], ["json", "JSON"]]) {
      const link = document.createElement("a");
      link.href = "/chats/" + currentChatId + "/export?format=" + format;
      link.textContent = "Export current chat (" + label + ")";
      link.style.display = "block";
      downloads.appendChild(link);
    }
  }
  settingsFields.appendChild(downloads);
}

// Web search: where SearXNG listens. The 🌐 Web box in the chat turns it
// on per message; here is only the address.
function addWebSetting(values) {
  const section = document.createElement("fieldset");
  section.className = "setting-group";

  const legend = document.createElement("legend");
  legend.textContent = "Web search";

  const field = document.createElement("input");
  field.type = "url"; // the browser checks it looks like an address
  field.name = "web_url";
  field.className = "setting-input";
  field.value = values.web_url;
  field.placeholder = "http://127.0.0.1:8888";

  const hint = document.createElement("p");
  hint.className = "hint";
  hint.textContent =
    "The address of your SearXNG. With the 🌐 Web box ticked, your question is " +
    "sent to it, and SearXNG asks search engines on the internet. Cerberus then " +
    "reads the best pages, but never pages on this computer or your home network. " +
    "Not running? Start it with: sudo docker start searxng";

  section.append(legend, field, hint);
  settingsFields.appendChild(section);
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
  summary.textContent = "Built-in prompts (read only)";

  const intro = document.createElement("p");
  intro.className = "hint";
  intro.textContent =
    "Everything else Cerberus tells the model, for each feature. Words in " +
    "{curly braces} are filled in by Cerberus. To change these, edit cerberus/prompts.py.";

  const list = document.createElement("div");
  details.append(summary, intro, list);

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

// The on/off features that use a second model. Each one is saved as two
// settings, "<key>_on" and "<key>_model" (see cerberus/settings.py), and
// gets the same kind of section in the dialog. A new feature = one more
// object in this list.
const MODEL_FEATURES = [
  {
    key: "helper",
    title: "Helper",
    label: "Use a Helper model for background jobs",
    // Any chat model can be the Helper. filter(Boolean) drops the "None"
    // choice of the chat dropdown, whose value is "" (and "" counts as false).
    models: () => [...modelSelect.options].map((option) => option.value).filter(Boolean),
    hint:
      "The Helper sorts your messages, writes chat titles, summaries and project " +
      "notes, so your chat model only has to answer. Pick a small, fast model " +
      "without thinking, like llama3.2:3b. Answers always come from the model " +
      "you choose in the chat. When it's off, the chat model does everything.",
  },
  {
    key: "eyes",
    title: "Eyes",
    label: "Let a vision model describe images for the chat model",
    // Only models that can see. visionModels comes from app.js.
    models: () => [...visionModels],
    hint:
      "When your chat model can't see images, the Eyes model looks at them " +
      "and tells it what they show, so you can ask about pictures with any " +
      "model. Pick a vision model, like gemma3:4b. Chat models that can see " +
      "get the images themselves.",
  },
];

// One section of the dialog: an on/off switch and the model it uses.
function addModelFeature(values, feature) {
  const section = document.createElement("fieldset");
  section.className = "setting-group";

  // <legend> is the title of a <fieldset>, drawn in its border.
  const legend = document.createElement("legend");
  legend.textContent = feature.title;

  // The switch. Settings are saved as text, so it becomes "yes" or "no".
  const toggle = document.createElement("label");
  toggle.className = "toggle";
  const on = document.createElement("input");
  on.type = "checkbox";
  on.name = feature.key + "_on";
  on.checked = values[on.name] === "yes";
  toggle.append(on, " " + feature.label);

  const select = document.createElement("select");
  select.name = feature.key + "_model";
  const models = feature.models();
  select.appendChild(new Option(models.length ? "Pick a model..." : "No fitting models installed", ""));
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

  const hint = document.createElement("p");
  hint.className = "hint";
  hint.textContent = feature.hint;

  section.append(legend, toggle, select, hint);
  settingsFields.appendChild(section);
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
