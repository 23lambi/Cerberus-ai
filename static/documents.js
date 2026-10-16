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
  document.dispatchEvent(new CustomEvent("document-added", { detail: data }));
  return true;
}

documentFile.addEventListener("change", async () => {
  for (const file of documentFile.files) {
    await uploadFile(file);
    await loadDocuments();
  }
  documentFile.value = "";
});

async function removeDocument(doc) {
  if (!confirm("Remove " + doc.name + " from Cerberus?")) return;

  await fetch("/documents/" + doc.id, { method: "DELETE" });
  documentStatus.textContent = "";
  loadDocuments();
}
