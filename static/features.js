// Each sidebar button opens its own panel. Only the active panel is visible.

const featureButtons = document.querySelectorAll("[data-feature]");
const panels = document.querySelectorAll(".panel");
let activeFeature = "chat";

function updateFeatureSelection() {
  for (const button of featureButtons) {
    const selected = button.dataset.feature === activeFeature;
    button.classList.toggle("active", selected);
    if (selected) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
}

function showFeature(name) {
  activeFeature = name;
  for (const panel of panels) {
    panel.classList.toggle("active", panel.id === "panel-" + name);
  }
  if (name === "memory") loadMemories();
  if (name === "documents") loadDocuments();
  updateFeatureSelection();
  if (name === "models") loadModelsPanel();
}

// button.dataset.feature reads the button's data-feature="..." attribute.
for (const button of featureButtons) {
  button.addEventListener("click", () => showFeature(button.dataset.feature));
}

// What you see when the page opens.
showFeature("chat");
