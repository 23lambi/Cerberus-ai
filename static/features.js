// Each feature has a button with data-feature="name" and a panel with id="panel-name".
const featureButtons = document.querySelectorAll("[data-feature]");
const panels = document.querySelectorAll(".panel");
const tabButtons = document.querySelectorAll("[data-tab]");
const tabBodies = document.querySelectorAll(".tab-body");

function showFeature(name) {
  for (const panel of panels) {
    panel.classList.toggle("active", panel.id === "panel-" + name);
  }
  for (const button of featureButtons) {
    button.classList.toggle("active", button.dataset.feature === name);
  }
  if (name === "memory") {
    loadMemories();
    loadDocuments();
  }
}

function showTab(name) {
  for (const body of tabBodies) {
    body.classList.toggle("active", body.id === "tab-" + name);
  }
  for (const button of tabButtons) {
    button.classList.toggle("active", button.dataset.tab === name);
  }
}

for (const button of featureButtons) {
  button.addEventListener("click", () => showFeature(button.dataset.feature));
}
for (const button of tabButtons) {
  button.addEventListener("click", () => showTab(button.dataset.tab));
}

showFeature("chat");
showTab("memories");
