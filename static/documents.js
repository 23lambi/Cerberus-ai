// The Documents tab: upload files for Cerberus to read, list them and
// remove them. The + button in the chat uses the same file picker.

const documentList = document.getElementById("document-list");
const documentFile = document.getElementById("document-file");
const documentStatus = document.getElementById("document-status");

async function loadDocuments() {
  document.getElementById("document-scope").textContent = currentProject
    ? "Files for project: " + currentProject.name + ". Other projects cannot retrieve these files."
    : "Files for All chats. Enter a project to manage its documents.";
  const response = await fetch("/documents" + (currentProject ? "?project_id=" + currentProject.id : ""));
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
    const open = document.createElement("button");
    open.textContent = doc.editable ? "Edit" : "Read / copy";
    open.addEventListener("click", () => openDocumentEditor(doc.id));
    li.appendChild(open);
    li.appendChild(del);
    documentList.appendChild(li);
  }
}

async function uploadFile(file, chatId = null) {
  documentStatus.textContent = "Reading and indexing " + file.name + "...";

  // The file itself is the request body; its name goes in the URL.
  // encodeURIComponent makes names with spaces or "&" safe in a URL.
  const projectId = currentProject ? currentProject.id : null;
  const response = await fetch("/documents?name=" + encodeURIComponent(file.name) + (chatId ? "&chat_id=" + chatId : projectId ? "&project_id=" + projectId : ""), {
    method: "POST",
    body: file,
  });
  const data = await response.json();

  if (!response.ok) {
    documentStatus.textContent = file.name + ": " + data.detail;
    return false;
  }

  documentStatus.textContent = chatId
    ? file.name + ": attached to this chat only. Ask a question about it."
    : data.searchable_by_meaning
    ? file.name + ": done, " + data.chunks + " parts."
    : file.name + ": saved, but only searchable by words. Run: ollama pull nomic-embed-text";

  // NEW: tell the rest of the page a document was added (app.js shows the chip).
  // A CustomEvent is our own event; anyone can listen to it, like to "click".
  document.dispatchEvent(new CustomEvent("document-added", { detail: {...data, chat_id: chatId} }));
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

  const response = await fetch("/documents/" + doc.id, { method: "DELETE" });
  if (!response.ok) { documentStatus.textContent = await responseError(response); return; }
  documentStatus.textContent = "";
  loadDocuments();
}

// Previews are read-only. Citation snapshots work even after the original is gone.
const filePreview = document.getElementById("file-preview");
let previewRequest = 0;
async function openFilePreview(documentId, source = null) {
  const requestId = ++previewRequest;
  const title = document.getElementById("file-preview-title");
  const text = document.getElementById("file-preview-text");
  const status = document.getElementById("file-preview-status");
  const current = document.getElementById("file-preview-current");
  if (!filePreview.open) filePreview.showModal();
  title.textContent = source ? source.name : "File preview";
  text.textContent = source ? source.text : "";
  current.hidden = !source;
  current.onclick = () => openFilePreview(documentId);
  status.textContent = source
    ? "Source [" + source.number + "]: exact text supplied for this answer. The current document may have changed."
    : "Loading file…";
  if (source) return;
  try {
    const doc = await editorRequest("/documents/" + documentId);
    if (requestId !== previewRequest || !filePreview.open) return;
    title.textContent = doc.name;
    text.textContent = doc.content; // display file text without executing HTML or code
    status.textContent = doc.editable ? "Current saved Markdown · version " + doc.revision : "Extracted text from the uploaded file.";
  } catch (error) {
    if (requestId === previewRequest) status.textContent = error.message;
  }
}
document.getElementById("file-preview-close").addEventListener("click", () => {
  previewRequest++;
  filePreview.close();
});
filePreview.addEventListener("cancel", () => { previewRequest++; });

// The editor keeps its scope and revision even if other page state changes.
const editor = document.getElementById("document-editor");
const editorName = document.getElementById("editor-name");
const editorContent = document.getElementById("editor-content");
const editorStatus = document.getElementById("editor-status");
let editingDocument = null;
let editorSavedName = "";
let editorSavedContent = "";
let editorHistory = [];
let editorProposal = null;
let editorBusy = false;

function editorDirty() {
  return editorName.value !== editorSavedName || editorContent.value !== editorSavedContent;
}

function clearProposal() {
  editorProposal = null;
  document.getElementById("editor-proposal").hidden = true;
}

async function editorRequest(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(await responseError(response));
  return response.json();
}

async function editorOperation(work) {
  if (editorBusy) return;
  editorBusy = true;
  for (const control of editor.querySelectorAll("button, input, textarea, select")) control.disabled = true;
  try { await work(); }
  catch (error) { editorStatus.textContent = error.message; }
  finally {
    editorBusy = false;
    for (const control of editor.querySelectorAll("button, input, textarea, select")) control.disabled = false;
  }
}

async function loadEditorHistory() {
  const select = document.getElementById("editor-versions");
  select.replaceChildren(new Option("Load a saved version…", ""));
  editorHistory = [];
  if (!editingDocument.id) return;
  const data = await editorRequest("/documents/" + editingDocument.id + "/versions");
  editorHistory = data.versions;
  for (const version of editorHistory) {
    select.add(new Option("Version " + version.revision + " · " + version.created_at, String(version.revision)));
  }
}

async function openDocumentEditor(id = null, content = "") {
  if (editorBusy || editor.open) return;
  editingDocument = {id: null, project_id: currentProject ? currentProject.id : null, revision: 0};
  editorName.value = "notes.md";
  editorContent.value = content;
  editorStatus.textContent = "";
  document.getElementById("editor-preview").hidden = true;
  clearProposal();
  editorSavedName = editorName.value;
  editorSavedContent = "";
  document.getElementById("editor-scope").textContent = currentProject ? "Project: " + currentProject.name : "All chats";
  editor.showModal();
  await editorOperation(async () => {
    if (id !== null) {
      const doc = await editorRequest("/documents/" + id);
      editingDocument = doc.editable ? doc : {id: null, project_id: doc.project_id, revision: 0};
      editorName.value = doc.editable ? doc.name : doc.name.replace(/\.[^.]+$/, "") + ".md";
      editorContent.value = doc.content;
      editorStatus.textContent = doc.editable ? "" : "Editable copy. The original upload is preserved; save to create a new document.";
      editorSavedName = editorName.value;
      editorSavedContent = doc.editable ? doc.content : "";
    }
    await loadEditorHistory();
  });
}

function closeDocumentEditor(event) {
  if (event) event.preventDefault();
  if (editorBusy) return;
  if (editorDirty() && !confirm("Discard unsaved document changes?")) return;
  editor.close();
}

document.getElementById("editor-close").addEventListener("click", closeDocumentEditor);
editor.addEventListener("cancel", closeDocumentEditor);
window.addEventListener("beforeunload", event => {
  if (editor.open && (editorDirty() || editorBusy)) { event.preventDefault(); event.returnValue = ""; }
});
document.getElementById("new-document").addEventListener("click", () => openDocumentEditor());
document.getElementById("open-project-documents").addEventListener("click", () => {
  showFeature("memory"); showTab("documents");
});
document.getElementById("editor-save").addEventListener("click", () => editorOperation(async () => {
  const doc = await editorRequest(editingDocument.id ? "/documents/" + editingDocument.id : "/documents/workspace", {
    method: editingDocument.id ? "PUT" : "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({name: editorName.value, content: editorContent.value,
      project_id: editingDocument.project_id, revision: editingDocument.revision}),
  });
  editingDocument = doc;
  editorName.value = doc.name;
  editorSavedName = doc.name; editorSavedContent = doc.content;
  clearProposal();
  editorStatus.textContent = "Saved version " + doc.revision + (doc.searchable_by_meaning ? "." : ". Search uses words until the embedding model is available.");
  await loadEditorHistory(); await loadDocuments();
}));
document.getElementById("editor-preview-toggle").addEventListener("click", () => {
  const preview = document.getElementById("editor-preview");
  preview.innerHTML = DOMPurify.sanitize(marked.parse(editorContent.value));
  preview.hidden = !preview.hidden;
});
document.getElementById("editor-versions").addEventListener("change", event => {
  const version = editorHistory.find(item => String(item.revision) === event.target.value);
  if (!version || (editorDirty() && !confirm("Replace unsaved changes with this version?"))) return;
  editorName.value = version.name; editorContent.value = version.content;
  clearProposal();
  editorStatus.textContent = "Loaded version " + version.revision + ". Save to restore it as a new version.";
});
document.getElementById("editor-propose").addEventListener("click", () => editorOperation(async () => {
  if (!editingDocument.id || editorDirty()) throw new Error("Save your document before requesting an edit.");
  const model = document.getElementById("model").value;
  if (!model) throw new Error("Select a chat model first.");
  clearProposal();
  editorStatus.textContent = "Preparing proposed changes…";
  editorProposal = await editorRequest("/documents/" + editingDocument.id + "/proposals", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({model, instruction: document.getElementById("editor-instruction").value, revision: editingDocument.revision}),
  });
  document.getElementById("editor-diff").textContent = editorProposal.diff || "No changes proposed.";
  document.getElementById("editor-proposal").hidden = false;
  editorStatus.textContent = "Review the proposed changes. Your saved document has not changed.";
}));
document.getElementById("editor-apply").addEventListener("click", () => editorOperation(async () => {
  if (!editorProposal || editorDirty()) throw new Error("The editor changed. Save it and request a fresh proposal.");
  const doc = await editorRequest("/documents/" + editingDocument.id + "/proposals/" + editorProposal.id + "/apply", {method: "POST"});
  editingDocument = doc;
  editorName.value = doc.name; editorContent.value = doc.content;
  editorSavedName = doc.name; editorSavedContent = doc.content;
  clearProposal();
  editorStatus.textContent = "Applied and saved version " + doc.revision + ".";
  await loadEditorHistory(); await loadDocuments();
}));
document.getElementById("editor-discard").addEventListener("click", clearProposal);
editorContent.addEventListener("input", () => { clearProposal(); document.getElementById("editor-preview").hidden = true; });
editorName.addEventListener("input", clearProposal);
