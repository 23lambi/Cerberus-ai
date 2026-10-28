// Switching between panels (Chat, Reverse, Memory) and between the tabs
// inside the Memory panel. Only the panel with the class "active" is
// visible; style.css hides all the others.

// Each feature has a button with data-feature="name" and a panel with id="panel-name".
// querySelectorAll("[data-feature]") finds every element with that attribute.
const featureButtons = document.querySelectorAll("[data-feature]");
const panels = document.querySelectorAll(".panel");
const tabButtons = document.querySelectorAll("[data-tab]");
const tabBodies = document.querySelectorAll(".tab-body");

function showFeature(name) {
  // classList.toggle(cls, true/false) adds or removes the class.
  for (const panel of panels) {
    panel.classList.toggle("active", panel.id === "panel-" + name);
  }
  for (const button of featureButtons) {
    button.classList.toggle("active", button.dataset.feature === name);
  }
  // Load fresh lists every time the Memory panel opens.
  if (name === "memory") {
    loadMemories();
    loadDocuments();
  }
  if (name === "models") loadModelsPanel();
}

function showTab(name) {
  for (const body of tabBodies) {
    body.classList.toggle("active", body.id === "tab-" + name);
  }
  for (const button of tabButtons) {
    button.classList.toggle("active", button.dataset.tab === name);
  }
}

// button.dataset.feature reads the button's data-feature="..." attribute.
for (const button of featureButtons) {
  button.addEventListener("click", () => showFeature(button.dataset.feature));
}
for (const button of tabButtons) {
  button.addEventListener("click", () => showTab(button.dataset.tab));
}

// What you see when the page opens.
showFeature("chat");
showTab("memories");
