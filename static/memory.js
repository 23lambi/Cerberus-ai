// The Memories tab: shows what Cerberus remembers, and lets you add,
// edit and forget memories. Each action calls the server, then redraws
// the list from the server's answer.

const memoryList = document.getElementById("memory-list");
const memoryAddForm = document.getElementById("memory-add");
const memoryInput = document.getElementById("memory-input");

async function loadMemories() {
  const response = await fetch("/memories");
  const data = await response.json();

  memoryList.innerHTML = "";

  if (data.memories.length === 0) {
    const li = document.createElement("li");
    li.textContent = "Nothing saved yet. Try: \"Remember that I study computer science.\"";
    memoryList.appendChild(li);
    return;
  }

  // One row per memory: the text, an Edit button and a Forget button.
  for (const memory of data.memories) {
    const li = document.createElement("li");

    const text = document.createElement("span");
    text.className = "text";
    text.textContent = memory.text;

    const edit = document.createElement("button");
    edit.textContent = "Edit";
    // An arrow function, so each button remembers its own memory.
    edit.addEventListener("click", () => editMemory(memory));

    const del = document.createElement("button");
    del.textContent = "Forget";
    del.addEventListener("click", () => forgetMemory(memory));

    li.appendChild(text);
    li.appendChild(edit);
    li.appendChild(del);
    memoryList.appendChild(li);
  }
}

async function editMemory(memory) {
  // prompt() returns null when the user presses Cancel.
  const text = prompt("Edit memory:", memory.text);
  if (text === null || !text.trim()) return;

  await fetch("/memories/" + memory.id, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: text }),
  });
  loadMemories();
}

async function forgetMemory(memory) {
  if (!confirm("Forget this?\n\n" + memory.text)) return;

  await fetch("/memories/" + memory.id, { method: "DELETE" });
  loadMemories();
}

memoryAddForm.addEventListener("submit", async (event) => {
  event.preventDefault(); // handle the form here instead of reloading the page
  const text = memoryInput.value.trim();
  if (!text) return;

  memoryInput.value = "";
  await fetch("/memories", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: text }),
  });
  loadMemories();
});
