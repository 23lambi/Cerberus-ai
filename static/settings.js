const settingsDialog = document.getElementById("settings-dialog");
const settingsForm = document.getElementById("settings-form");
const settingsFields = document.getElementById("settings-fields");
const openSettingsButton = document.getElementById("open-settings");
const resetSettingsButton = document.getElementById("settings-reset");
const cancelSettingsButton = document.getElementById("settings-cancel");

const SETTING_LABELS = {
  system_prompt: "Personality (normal chat)",
  thinker_prompt: "Thinker",
  coder_prompt: "Coder",
  critic_prompt: "Critic",
  judge_prompt: "Judge",
};

function fillSettings(values) {
  settingsFields.innerHTML = "";

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
}

async function openSettings() {
  const response = await fetch("/settings");
  const values = await response.json();
  fillSettings(values);
  settingsDialog.showModal();
}

settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const values = {};
  for (const textarea of settingsFields.querySelectorAll("textarea")) {
    values[textarea.name] = textarea.value;
  }

  await fetch("/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(values),
  });

  settingsDialog.close();
});

resetSettingsButton.addEventListener("click", async () => {
  if (!confirm("Reset all prompts to the defaults?")) return;

  const response = await fetch("/settings/reset", { method: "POST" });
  const values = await response.json();
  fillSettings(values);
});

cancelSettingsButton.addEventListener("click", () => settingsDialog.close());
openSettingsButton.addEventListener("click", openSettings);
