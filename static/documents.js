// The Documents screen: upload files for Cerberus to read, list them and
// remove them. The + button in the chat uses the same file picker.

const documentList = document.getElementById("document-list");
const documentFile = document.getElementById("document-file");
const documentStatus = document.getElementById("document-status");
const documentFilter = document.getElementById("document-filter");

// The last list from the server. The filter only redraws it, so typing
// stays instant and never asks the server again.
let loadedDocuments = [];

async function loadDocuments() {
  const response = await fetch("/documents" + (currentProject ? "?project_id=" + currentProject.id : ""));
  const data = await response.json();
  loadedDocuments = data.documents;
  showDocumentScope();
  drawDocuments();
}

// "All chats · 3 documents" or "Project: Thesis · 1 document", and who uses them.
function showDocumentScope() {
  const count = loadedDocuments.length;
  const where = currentProject ? "Project: " + currentProject.name : "All chats";
  const scope = document.getElementById("document-scope");
  scope.replaceChildren(
    makeBox("document-scope-name", where + " · " + count + (count === 1 ? " document" : " documents")),
    makeBox("hint", currentProject
      ? "Only this project's chats use them. Other projects never see them."
      : "Chats outside projects use them. Open a project for its own documents.")
  );
}

// The documents that fit the filter: title, file name or kind.
function filteredDocuments(documents, text) {
  const query = text.trim().toLowerCase();
  if (!query) return documents;
  return documents.filter((doc) => {
    const kind = (DOCUMENT_KINDS[doc.kind] || DOCUMENT_KINDS.upload).label;
    return [doc.title, doc.name, kind].join(" ").toLowerCase().includes(query);
  });
}

function drawDocuments() {
  documentList.innerHTML = "";
  // No documents at all: no filter, but a short welcome.
  documentFilter.closest("label").hidden = loadedDocuments.length === 0;
  if (loadedDocuments.length === 0) {
    const li = document.createElement("li");
    li.className = "document-empty";
    li.append(
      makeBox("document-title", "No documents yet"),
      makeBox("hint", "Upload files or drop them below, write a new note, or run Research: " +
        "its reports are saved here. Your chats then use them as sources.")
    );
    documentList.appendChild(li);
    return;
  }
  const shown = filteredDocuments(loadedDocuments, documentFilter.value);
  if (shown.length === 0) {
    const li = document.createElement("li");
    li.className = "document-empty";
    li.textContent = "No documents match \u201c" + documentFilter.value.trim() + "\u201d.";
    documentList.appendChild(li);
    return;
  }
  for (const doc of shown) {
    documentList.appendChild(documentRow(doc));
  }
}

documentFilter.addEventListener("input", drawDocuments);
// Escape empties the filter, like most search boxes.
documentFilter.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && documentFilter.value) {
    documentFilter.value = "";
    drawDocuments();
  }
});

// What kind of document it is (the server decides: cerberus/storage/keeper.py).
const DOCUMENT_KINDS = {
  upload: { label: "Uploaded file", icon: "#i-file" },
  note: { label: "Note", icon: "#i-book" },
  report: { label: "Research report", icon: "#i-globe" },
};

// One document: click it to open it, Ask about it in a new chat, and
// more in the ⋯ menu.
function documentRow(doc) {
  const kind = DOCUMENT_KINDS[doc.kind] || DOCUMENT_KINDS.upload;
  const li = document.createElement("li");
  li.className = "document-row";

  // The title and details are one big button: the whole left side opens it.
  const open = document.createElement("button");
  open.type = "button";
  open.className = "document-open";
  // A note opens in the editor; a file shows the text Cerberus read from it.
  open.title = doc.editable ? "Open in the editor" : "Show the text Cerberus read from this file";
  open.addEventListener("click", () => (doc.editable ? openDocumentEditor(doc.id) : openFilePreview(doc.id)));

  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("class", "icon");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", kind.icon);
  icon.appendChild(use);

  // An uploaded file's title is its name already; a note also shows its file name.
  const details = [
    doc.kind === "upload" ? "" : doc.name,
    formatBytes(doc.size), // models.js; "" when unknown
    (doc.editable ? "edited " : "added ") + friendlyDate(doc.updated_at || doc.created_at),
  ].filter(Boolean);
  const words = document.createElement("span");
  words.className = "document-words";
  words.append(makeBox("document-title", doc.title || doc.name), makeBox("document-meta", details.join(" · ")));
  open.append(icon, words);

  const label = makeBox("document-kind", kind.label);

  const ask = document.createElement("button");
  ask.type = "button";
  ask.textContent = "Ask";
  ask.title = "Start a chat with this document attached: the model reads all of it";
  ask.addEventListener("click", () => askAboutDocument(doc));

  li.append(open, label, ask, documentMenu(doc));
  return li;
}

// The ⋯ menu. <details> opens and closes by itself (also with the
// keyboard); we only close it when you click somewhere else.
function documentMenu(doc) {
  const menu = document.createElement("details");
  menu.className = "row-menu";
  const summary = document.createElement("summary");
  summary.textContent = "⋯";
  summary.setAttribute("aria-label", "More for " + (doc.title || doc.name));
  const items = document.createElement("div");
  items.className = "row-menu-items";

  const item = (text, action) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    button.addEventListener("click", () => {
      menu.open = false;
      action();
    });
    items.appendChild(button);
  };
  if (!doc.editable) item("Edit a copy", () => openDocumentEditor(doc.id));
  item("Remove", () => removeDocument(doc));

  menu.append(summary, items);
  closeMenusOnClickOutside();
  return menu;
}

// Closes an open ⋯ menu when you click anywhere outside it. Set up once,
// with the first menu (not when this file loads: the tests load it without a page).
let menusClose = false;
function closeMenusOnClickOutside() {
  if (menusClose) return;
  menusClose = true;
  document.addEventListener("click", (event) => {
    for (const menu of document.querySelectorAll("details.row-menu[open]")) {
      if (!menu.contains(event.target)) menu.open = false;
    }
  });
}

// "2026-10-30T14:05:00" -> "today 14:05", "yesterday 09:12", "3 days ago",
// or a date. Dates are saved in this computer's time, so new Date() reads them right.
function friendlyDate(text, now = new Date()) {
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return text;
  const midnight = (day) => new Date(day.getFullYear(), day.getMonth(), day.getDate());
  // Whole days between the two midnights; round() absorbs summer-time changes.
  const days = Math.round((midnight(now) - midnight(date)) / 86400000);
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (days === 0) return "today " + time;
  if (days === 1) return "yesterday " + time;
  if (days > 1 && days < 7) return days + " days ago";
  return date.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
}

// Ask: a new chat with a copy of the document attached (the + button's
// way), so the model reads all of it, not only the pieces search finds.
async function askAboutDocument(doc) {
  if (controller || attachmentUploads) {
    documentStatus.textContent = "Wait until the current answer is finished, then try again.";
    return;
  }
  newChat(); // app.js: opens the chat panel with an empty chat
  try {
    await ensureChat(); // the chat must exist on the server to attach to it
    const attached = await editorRequest("/documents/" + doc.id + "/attach", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: currentChatId }),
    });
    // app.js shows the attachment chip for this event, as after the + button.
    document.dispatchEvent(new CustomEvent("document-added", { detail: { ...attached, chat_id: currentChatId } }));
    attachStatus.textContent = (doc.title || doc.name) + " is attached: the model reads all of it. Ask anything.";
    loadChats();
  } catch (error) {
    attachStatus.textContent = error.message;
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

// Several files, one after the other, so the status line shows each in
// turn. A file that fails doesn't stop the others, and its reason stays
// on screen at the end instead of being replaced by the next file.
let documentUploads = false;
async function uploadDocuments(files) {
  if (documentUploads || files.length === 0) return;
  documentUploads = true;
  const problems = [];
  let added = 0;
  try {
    for (const file of files) {
      try {
        if (await uploadFile(file)) added += 1;
        else problems.push(documentStatus.textContent);
      } catch (error) {
        problems.push(file.name + ": " + error.message);
      }
      await loadDocuments();
    }
  } finally {
    documentUploads = false;
  }
  // One file that worked: keep uploadFile's own message (it may give a tip).
  if (files.length > 1 || problems.length) {
    const done = added ? added + (added === 1 ? " file added." : " files added.") : "";
    documentStatus.textContent = [done, ...problems].filter(Boolean).join(" ");
  }
}

document.getElementById("upload-documents").addEventListener("click", () => documentFile.click());

// "change" fires when the user has picked files.
documentFile.addEventListener("change", async () => {
  // [...files]: a copy, because clearing the picker below empties the list.
  const files = [...documentFile.files];
  documentFile.value = ""; // so picking the same file again fires "change" again
  await uploadDocuments(files);
});

// Drag and drop: anywhere on the Docs page. When you drop a file on a
// page, the browser opens it by itself; preventDefault() on "dragover"
// says: drops are handled here. The drop area lights up meanwhile.
const documentsPanel = document.getElementById("panel-documents");
const documentDrop = document.getElementById("document-drop");
let dragDepth = 0; // dragenter/dragleave also fire for every element inside

function carriesFiles(event) {
  // Dragging selected text or a link is not an upload.
  return event.dataTransfer && [...event.dataTransfer.types].includes("Files");
}

documentsPanel.addEventListener("dragenter", (event) => {
  if (!carriesFiles(event)) return;
  dragDepth += 1;
  documentDrop.classList.add("dragging");
});
documentsPanel.addEventListener("dragover", (event) => {
  if (carriesFiles(event)) event.preventDefault();
});
documentsPanel.addEventListener("dragleave", (event) => {
  if (!carriesFiles(event)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) documentDrop.classList.remove("dragging");
});
documentsPanel.addEventListener("drop", (event) => {
  if (!carriesFiles(event)) return;
  event.preventDefault();
  dragDepth = 0;
  documentDrop.classList.remove("dragging");
  uploadDocuments([...event.dataTransfer.files]);
});
documentDrop.addEventListener("click", () => documentFile.click());

async function removeDocument(doc) {
  if (!confirm("Remove " + (doc.title || doc.name) + " from Cerberus?")) return;

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
  const link = document.getElementById("file-preview-link");
  const fromWeb = Boolean(source && source.kind === "web");
  if (!filePreview.open) filePreview.showModal();
  title.textContent = source ? source.name : "File preview";
  text.textContent = source ? source.text : "";
  // A document can be reopened as it is now; a web page is opened on its site.
  current.hidden = !source || fromWeb;
  current.onclick = () => openFilePreview(documentId);
  // Only real web addresses become a link. "javascript:..." would be code
  // that runs on click, so saved data never gets to choose that.
  const safeUrl = fromWeb && /^https?:\/\//i.test(source.url || "");
  link.hidden = !safeUrl;
  link.href = safeUrl ? source.url : "#";
  if (fromWeb) {
    status.textContent = "Source [" + source.number + "]: the exact text taken from this web page for this answer. The page may have changed since.";
  } else {
    status.textContent = source
      ? "Source [" + source.number + "]: exact text supplied for this answer. The current document may have changed."
      : "Loading file…";
  }
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
