// The Documents tab: upload files for Cerberus to read, list them and
// remove them. The + button in the chat uses the same file picker.

const documentList = document.getElementById("document-list");
const documentFile = document.getElementById("document-file");
const documentStatus = document.getElementById("document-status");

async function loadDocuments() {
  const response = await fetch("/documents");
  const data = await response.json();

  documentList.innerHTML = "";

  if (data.documents.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No documents yet. Pick a .txt, .md or .pdf file above.";
    documentList.appendChild(li);
    return;
  }

  for (const doc of data.documents) {
    const li = document.createElement("li");

    const text = document.createElement("span");
    text.className = "text";
    // created_at is "2026-10-17T12:00:00"; slice(0, 10) keeps only the date.
    text.textContent = doc.name + " (" + doc.chunks + " parts, " + doc.created_at.slice(0, 10) + ")";

    const del = document.createElement("button");
    del.textContent = "Remove";
    del.addEventListener("click", () => removeDocument(doc));

    li.appendChild(text);
    li.appendChild(del);
    documentList.appendChild(li);
  }
}

async function uploadFile(file) {
  documentStatus.textContent = "Reading and indexing " + file.name + "...";

  // The file itself is the request body; its name goes in the URL.
  // encodeURIComponent makes names with spaces or "&" safe in a URL.
  const response = await fetch("/documents?name=" + encodeURIComponent(file.name), {
    method: "POST",
    body: file,
  });
  const data = await response.json();

  if (!response.ok) {
    documentStatus.textContent = file.name + ": " + data.detail;
    return false;
  }

  documentStatus.textContent = data.searchable_by_meaning
    ? file.name + ": done, " + data.chunks + " parts."
    : file.name + ": saved, but only searchable by words. Run: ollama pull nomic-embed-text";

  // NEW: tell the rest of the page a document was added (app.js shows the chip).
  // A CustomEvent is our own event; anyone can listen to it, like to "click".
  document.dispatchEvent(new CustomEvent("document-added", { detail: data }));
  return true;
}

// "change" fires when the user has picked files.
documentFile.addEventListener("change", async () => {
  // One at a time, so the status line shows each file in turn.
  for (const file of documentFile.files) {
    await uploadFile(file);
    await loadDocuments();
  }
  documentFile.value = ""; // so picking the same file again fires "change" again
});

async function removeDocument(doc) {
  if (!confirm("Remove " + doc.name + " from Cerberus?")) return;

  await fetch("/documents/" + doc.id, { method: "DELETE" });
  documentStatus.textContent = "";
  loadDocuments();
}
