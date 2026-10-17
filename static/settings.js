// The Settings dialog. Text settings are built from SETTING_LABELS, so a
// new one only needs one line here (and a default in cerberus/settings.py).
// The on/off features with a model (Helper, Eyes) are built from MODEL_FEATURES.

const settingsDialog = document.getElementById("settings-dialog");
const settingsForm = document.getElementById("settings-form");
const settingsFields = document.getElementById("settings-fields");
const openSettingsButton = document.getElementById("open-settings");
const resetSettingsButton = document.getElementById("settings-reset");
const cancelSettingsButton = document.getElementById("settings-cancel");

// Setting key (as the server calls it) -> label shown to the user.
const SETTING_LABELS = {
  system_prompt: "Cerberus's personality",
};

// Builds one field per setting, filled with the current values.
function fillSettings(values) {
  settingsFields.innerHTML = "";

  // Object.entries turns { a: 1 } into [["a", 1]], so we get key and label.
  for (const [key, label] of Object.entries(SETTING_LABELS)) {
    const wrapper = document.createElement("label");
    wrapper.className = "setting";
    wrapper.textContent = label;

    const textarea = document.createElement("textarea");
    textarea.name = key;
    textarea.rows = 4;
    textarea.value = values[key];

    wrapper.appendChild(textarea);
    settingsFields.appendChild(wrapper);
  }

  for (const feature of MODEL_FEATURES) {
    addModelFeature(values, feature);
  }
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
    // Any chat model can be the Helper.
    models: () => [...modelSelect.options].map((option) => option.value),
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
});

cancelSettingsButton.addEventListener("click", () => settingsDialog.close());
openSettingsButton.addEventListener("click", openSettings);
