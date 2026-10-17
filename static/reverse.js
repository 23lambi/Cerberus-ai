// The Reverse panel: drop a program, see what Cerberus finds inside it,
// and ask the model about it. The file is only read, never run.

const dropZone = document.getElementById("drop-zone");
const reverseFile = document.getElementById("reverse-file");
const reverseStatus = document.getElementById("reverse-status");
const reverseResult = document.getElementById("reverse-result");

let droppedFile = null; // the file on screen itself, for a ClamAV scan
let reverseFacts = null; // the facts of the file on screen
let reverseHistory = []; // the questions and answers about that file
let reverseController = null; // stops a running answer, like in the chat

async function analyzeFile(file) {
  reverseStatus.textContent = "Reading " + file.name + "...";
  reverseResult.innerHTML = "";

  // Like documents: the file is the body, its name goes in the URL.
  const response = await fetch("/reverse?name=" + encodeURIComponent(file.name), {
    method: "POST",
    body: file,
  });
  const data = await response.json();

  if (!response.ok) {
    reverseStatus.textContent = file.name + ": " + data.detail;
    return;
  }
  reverseStatus.textContent = "";
  droppedFile = file;
  reverseFacts = data;
  reverseHistory = []; // a new file: a new conversation
  showFacts(data);
}

// The facts: name, type, size, fingerprint and the strings.
function showFacts(facts) {
  const title = document.createElement("h3");
  title.textContent = facts.name;

  const summary = document.createElement("p");
  summary.className = "facts";
  const parts = [facts.type];
  if (facts.details) parts.push(facts.details);
  parts.push(formatSize(facts.size));
  summary.textContent = parts.join(" · ");

  const hash = document.createElement("p");
  hash.className = "hint";
  hash.textContent = "sha256 " + facts.sha256;

  reverseResult.append(title, summary, hash, signsBox(facts), chatBox());

  // R2: what the imports say the program can do, then the imports.
  if (facts.capabilities.length > 0) {
    reverseResult.appendChild(capabilitiesBox(facts));
  }
  if (facts.disassembly) {
    reverseResult.appendChild(disassemblyBox(facts.disassembly));
  } else if (facts.type.startsWith("ELF") || facts.type.startsWith("PE")) {
    const note = document.createElement("p");
    note.className = "hint";
    note.textContent =
      "No disassembly: Cerberus reads Linux x86-64 programs for now, and packed programs hide their code.";
    reverseResult.appendChild(note);
  }
  if (facts.imports_total > 0) {
    reverseResult.appendChild(importsBox(facts));
  } else if (facts.type.startsWith("ELF") || facts.type.startsWith("PE")) {
    // A program without imports has everything built in ("statically
    // linked"), or hides them ("packed"), which malware likes to do.
    const note = document.createElement("p");
    note.className = "hint";
    note.textContent = "No imports found: the program is statically linked, or packed to hide them.";
    reverseResult.appendChild(note);
  }

  reverseResult.appendChild(stringsBox(facts));
}

// "Network: socket, connect" ... one line per group of abilities.
function capabilitiesBox(facts) {
  const box = document.createElement("div");
  box.className = "capabilities";

  const title = document.createElement("h4");
  title.textContent = "What it can do (from its imports)";
  box.appendChild(title);

  for (const group of facts.capabilities) {
    const row = document.createElement("p");
    const what = document.createElement("strong");
    what.textContent = group.what + ": ";
    // append() takes elements and plain text; plain text is always safe.
    row.append(what, group.functions.join(", "));
    box.appendChild(row);
  }

  const note = document.createElement("p");
  note.className = "hint";
  note.textContent =
    "This shows what the program is able to do, not what it really does. " +
    "Compilers add some of these to almost every program.";
  box.appendChild(note);
  return box;
}

// The assembly of main and the functions it calls, one line per
// instruction: address, instruction, and Cerberus's note after the ";".
function disassemblyBox(functions) {
  const lines = [];
  let count = 0;
  for (const fn of functions) {
    lines.push(fn.name + ":");
    for (const line of fn.lines) {
      let row = line.address.toString(16) + "  " + line.text;
      // padEnd fills with spaces, so all the notes start in one column.
      if (line.note) row = row.padEnd(44) + "; " + line.note;
      lines.push(row);
      count++;
    }
    lines.push("");
  }
  const title = "Disassembly (" + count + " instructions in " + functions.length + " functions)";
  return listBox(title, lines, "Filter, like: call, cmp, password", true);
}

// The imported functions, and the libraries they come from.
function importsBox(facts) {
  let title = "Imports (" + facts.imports_total + " from " + facts.libraries.join(", ") + ")";
  if (facts.imports_total > facts.imports.length) {
    title += ", showing the first " + facts.imports.length;
  }
  return listBox(title, facts.imports, "Filter imports, like: str, socket, File", false);
}

// 195312 -> "190.7 KB"
function formatSize(bytes) {
  if (bytes < 1024) return bytes + " bytes";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}

// The strings: each line is the offset as 8 hex digits, then the string.
// padStart(8, "0") turns "1a2b" into "00001a2b".
function stringsBox(facts) {
  let title = "Strings (" + facts.strings_total + ")";
  if (facts.strings_total > facts.strings.length) {
    title += ", showing the first " + facts.strings.length;
  }
  const lines = facts.strings.map((s) => s.offset.toString(16).padStart(8, "0") + "  " + s.text);
  return listBox(title, lines, "Filter strings, like: password, http, .so", true);
}

// A fold-out box with a list of lines and a filter to search them.
// Strings and imports both use it.
function listBox(title, lines, placeholder, open) {
  const details = document.createElement("details");
  details.open = open;

  const summary = document.createElement("summary");
  summary.textContent = title;

  const filter = document.createElement("input");
  filter.type = "search";
  filter.className = "strings-filter";
  filter.placeholder = placeholder;

  // A <pre> keeps the columns lined up. textContent (never innerHTML!):
  // a program can contain text like "<script>", and here it must stay text.
  const list = document.createElement("pre");
  list.className = "strings";

  function draw() {
    const word = filter.value.toLowerCase();
    const shown = lines.filter((line) => line.toLowerCase().includes(word));
    list.textContent = shown.length ? shown.join("\n") : "(nothing matches)";
  }
  filter.addEventListener("input", draw);
  draw();

  details.append(summary, filter, list);
  return details;
}

// ---------- Warning signs (R5) ----------

// The clues that a file may be harmful, a link to look up its fingerprint,
// and a button for a ClamAV scan. Never a "safe": no check can prove that.
function signsBox(facts) {
  const box = document.createElement("div");
  box.className = "signs";

  const title = document.createElement("h4");
  const warnings = facts.signs.filter((sign) => sign.level === "warn").length;
  title.textContent = warnings
    ? "Warning signs (" + warnings + ")"
    : "No warning signs found";
  box.appendChild(title);

  for (const sign of facts.signs) {
    const row = document.createElement("p");
    row.className = "sign-" + sign.level; // sign-warn or sign-info
    row.textContent = (sign.level === "warn" ? "⚠ " : "· ") + sign.text;
    box.appendChild(row);
  }

  const advice = document.createElement("p");
  advice.className = "hint";
  advice.textContent =
    "These are clues, not a verdict: no check can prove a file is safe. " +
    "Don't run files you don't trust. ";
  // A search for the fingerprint: VirusTotal shows what about 70 virus
  // scanners say. Only the hash is sent, never the file.
  const link = document.createElement("a");
  link.href = "https://www.virustotal.com/gui/file/" + facts.sha256;
  link.target = "_blank";
  link.rel = "noopener"; // the new tab can't control this page
  link.textContent = "Look up its fingerprint on VirusTotal";
  advice.appendChild(link);
  box.appendChild(advice);

  const scan = document.createElement("button");
  scan.type = "button";
  scan.className = "mini";
  scan.textContent = "Scan with ClamAV";
  const result = document.createElement("p");
  result.className = "hint";
  scan.addEventListener("click", () => scanWithClamav(scan, result));
  box.append(scan, result);
  return box;
}

async function scanWithClamav(button, result) {
  button.disabled = true;
  result.textContent = "ClamAV is scanning (loading its pattern list takes a moment)...";
  try {
    const response = await fetch("/reverse/clamav", { method: "POST", body: droppedFile });
    const data = await response.json();
    if (!data.available) {
      result.textContent =
        "ClamAV isn't installed. Install it with: sudo pacman -S clamav && sudo freshclam";
    } else if (data.error) {
      result.textContent = "ClamAV: " + data.error;
    } else if (data.found.length > 0) {
      result.className = "sign-warn";
      result.textContent = "⚠ ClamAV found known malware: " + data.found.join(", ");
    } else {
      result.textContent = "ClamAV found no known malware. New or unknown malware can still get past it.";
    }
  } catch (error) {
    result.textContent = "Could not reach the server.";
  } finally {
    button.disabled = false;
  }
}

// ---------- Asking the model about the file (R4) ----------

// The "Explain" button, the conversation, and a box for questions.
function chatBox() {
  const box = document.createElement("div");
  box.className = "reverse-chat";

  const explain = document.createElement("button");
  explain.type = "button";
  explain.className = "explain";
  explain.textContent = "Explain this program";

  const log = document.createElement("div");
  log.className = "reverse-log";

  const form = document.createElement("form");
  form.className = "reverse-form";
  const question = document.createElement("input");
  question.placeholder = "Ask about this file, like: what does it do with the network?";
  const send = document.createElement("button");
  send.textContent = "Send";
  form.append(question, send);

  explain.addEventListener("click", () => {
    explain.remove(); // one explanation is enough; then ask follow-ups
    askAboutFile("Explain what this file probably does, step by step.", log, send);
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    // One button, two jobs, like in the chat: while an answer runs, Stop.
    if (reverseController) {
      reverseController.abort();
      return;
    }
    const text = question.value.trim();
    if (!text) return;
    question.value = "";
    explain.remove();
    askAboutFile(text, log, send);
  });

  box.append(explain, log, form);
  return box;
}

async function askAboutFile(text, log, send) {
  // The model chosen in the chat (modelSelect is in app.js).
  const model = modelSelect.value;
  if (!model) {
    reverseStatus.textContent = "Please pick a model in the chat first.";
    return;
  }

  const asked = document.createElement("div");
  asked.className = "message";
  asked.textContent = "You: " + text;
  const bubble = document.createElement("div");
  bubble.className = "message";
  bubble.textContent = "Cerberus is reading the facts...";
  log.append(asked, bubble);

  reverseHistory.push({ role: "user", content: text });
  reverseController = new AbortController();
  send.textContent = "Stop";

  let result = null;
  try {
    const response = await fetch("/reverse/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: model,
        facts: reverseFacts,
        messages: reverseHistory,
        think: wantsThinking(), // the Think checkbox from the chat
        tools: wantsTools(), // and the Tools checkbox
      }),
      signal: reverseController.signal,
    });
    if (response.ok) {
      // The same code that reads answers in the chat (app.js).
      result = await readReply(response, bubble, "Cerberus:");
    } else {
      bubble.textContent = "Cerberus: the server answered with error " + response.status + ".";
    }
  } catch (error) {
    if (error.name === "AbortError") {
      bubble.textContent = "Cerberus: (stopped)";
    } else {
      bubble.textContent = "Cerberus: could not reach the server. Is it running?";
    }
  } finally {
    reverseController = null;
    send.textContent = "Send";
  }

  const reply = result ? finishReply(result, bubble, "Cerberus:") : null;
  if (reply === null) {
    reverseHistory.pop(); // no answer, so take the question back out
  } else {
    reverseHistory.push({ role: "assistant", content: reply });
  }
}

// ---------- Picking a file: click or drag and drop ----------

dropZone.addEventListener("click", () => reverseFile.click());

reverseFile.addEventListener("change", () => {
  if (reverseFile.files[0]) analyzeFile(reverseFile.files[0]);
  reverseFile.value = ""; // so picking the same file again works
});

// When you drop a file on a page, the browser opens it by itself.
// preventDefault() on "dragover" says: drops are handled here.
dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropZone.classList.add("dragging");
});

dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragging"));

dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("dragging");
  const file = event.dataTransfer.files[0];
  if (file) analyzeFile(file);
});
