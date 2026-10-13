const memoryDialog = document.getElementById("memory-dialog");
const memoryList = document.getElementById("memory-list");
const memoryAddForm = document.getElementById("memory-add");
const memoryInput = document.getElementById("memory-input");
const openMemoryButton = document.getElementById("open-memory");
const closeMemoryButton = document.getElementById("memory-close");

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

  for (const memory of data.memories) {
    const li = document.createElement("li");

    const text = document.createElement("span");
    text.className = "text";
    text.textContent = memory.text;

    const edit = document.createElement("button");
    edit.textContent = "Edit";
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
  event.preventDefault();
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

openMemoryButton.addEventListener("click", () => {
  loadMemories();
  memoryDialog.showModal();
});
closeMemoryButton.addEventListener("click", () => memoryDialog.close());
