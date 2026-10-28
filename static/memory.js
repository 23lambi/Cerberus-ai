// The Memory screen: shows what Cerberus remembers, and lets you add,
// edit and forget memories. Each action calls the server, then redraws
// the list from the server's answer.

const memoryList = document.getElementById("memory-list");
const memoryAddForm = document.getElementById("memory-add");
const memoryInput = document.getElementById("memory-input");
const memoryStatus = document.getElementById("memory-status");

// Every action goes through here. It returns the server's answer, or null
// when something went wrong; then the reason is shown under the form, so
// a failed change never just silently does nothing.
async function memoryRequest(url, options = {}) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    // fetch itself fails when the server can't be reached at all.
    memoryStatus.textContent = "Could not reach Cerberus. Is the server running?";
    return null;
  }
  if (!response.ok) {
    // responseError (app.js) turns the server's error into a sentence.
    memoryStatus.textContent = await responseError(response);
    return null;
  }
  memoryStatus.textContent = "";
  return response.json();
}

async function loadMemories() {
  const data = await memoryRequest("/memories");
  if (!data) return; // keep the old list on screen; the status says why

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

  const saved = await memoryRequest("/memories/" + memory.id, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: text }),
  });
  if (saved) loadMemories();
}

async function forgetMemory(memory) {
  if (!confirm("Forget this?\n\n" + memory.text)) return;

  const forgotten = await memoryRequest("/memories/" + memory.id, { method: "DELETE" });
  if (forgotten) loadMemories();
}

memoryAddForm.addEventListener("submit", async (event) => {
  event.preventDefault(); // handle the form here instead of reloading the page
  const text = memoryInput.value.trim();
  if (!text) return;

  const added = await memoryRequest("/memories", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: text }),
  });
  if (!added) return; // keep what was typed, so it can be sent again
  // Only now, after the save worked, empty the box.
  memoryInput.value = "";
  loadMemories();
});
