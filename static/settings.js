// The Settings dialog. Text settings are built from SETTING_LABELS, so a
// new one only needs one line here (and a default in cerberus/settings.py).
// The Helper has its own section, built by addHelperSettings.

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

  addHelperSettings(values);
}

// The Helper feature: an on/off switch and the model it uses.
function addHelperSettings(values) {
  const section = document.createElement("fieldset");
  section.className = "setting-group";

  // <legend> is the title of a <fieldset>, drawn in its border.
  const legend = document.createElement("legend");
  legend.textContent = "Helper";

  // The switch. Settings are saved as text, so it becomes "yes" or "no".
  const toggle = document.createElement("label");
  toggle.className = "toggle";
  const on = document.createElement("input");
  on.type = "checkbox";
  on.name = "helper_on";
  on.checked = values.helper_on === "yes";
  toggle.append(on, " Use a Helper model for background jobs");

  const select = document.createElement("select");
  select.name = "helper_model";
  const pick = new Option("Pick a model...", "");
  select.appendChild(pick);
  // Every installed model. app.js already loaded them into the chat
  // dropdown, so we copy its options instead of asking the server again.
  for (const option of modelSelect.options) {
    select.appendChild(new Option(option.value, option.value));
  }
  select.value = values.helper_model;
  // A model that was removed isn't in the list anymore.
  if (select.value !== values.helper_model) select.value = "";

  // The dropdown only matters while the Helper is on.
  select.disabled = !on.checked;
  on.addEventListener("change", () => {
    select.disabled = !on.checked;
  });

  const hint = document.createElement("p");
  hint.className = "hint";
  hint.textContent =
    "The Helper sorts your messages, writes chat titles, summaries and project " +
    "notes, so your chat model only has to answer. Pick a small, fast model " +
    "without thinking, like llama3.2:3b. Answers always come from the model " +
    "you choose in the chat. When it's off, the chat model does everything.";

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
