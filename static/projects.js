// Projects in the sidebar: create, enter, rename, leave and delete.
// Inside a project, new chats belong to it and share its notes.

const projectList = document.getElementById("project-list");
const projectBar = document.getElementById("project-bar");
const projectName = document.getElementById("project-name");
const projectsLabel = document.getElementById("projects-label");
const chatsLabel = document.getElementById("chats-label");

// currentProject lives in app.js, because loadChats and ensureChat need it.

async function loadProjects() {
  const response = await fetch("/projects");
  const data = await response.json();

  projectList.innerHTML = "";

  for (const project of data.projects) {
    const li = document.createElement("li");

    const title = document.createElement("span");
    title.className = "title";
    title.textContent = project.name;
    // The tooltip when you hover the name, like "3 chats".
    title.title = project.chats + (project.chats === 1 ? " chat" : " chats");

    const del = document.createElement("button");
    del.className = "delete";
    del.textContent = "×";
    del.title = "Delete project";

    li.addEventListener("click", () => enterProject(project));
    del.addEventListener("click", (event) => {
      event.stopPropagation(); // don't also enter the project we're deleting
      deleteProject(project);
    });

    li.appendChild(title);
    li.appendChild(del);
    projectList.appendChild(li);
  }
}

// Inside a project, the sidebar shows the project bar instead of the project list.
function showProjectMode() {
  const inside = currentProject !== null;
  projectBar.hidden = !inside;
  projectList.hidden = inside;
  projectsLabel.hidden = inside;
  projectName.textContent = inside ? currentProject.name : "";
  chatsLabel.textContent = inside ? "Project chats" : "Chats";
}

function enterProject(project) {
  if (controller || attachmentUploads) return;
  currentProject = project;
  showProjectMode();
  newChat(); // newChat also reloads the chat list, now with this project's chats
}

async function leaveProject() {
  if (controller || attachmentUploads) return;
  currentProject = null;
  showProjectMode();
  newChat(); // back to the normal chats
  await loadProjects(); // the chat counts may have changed
}

async function createProject() {
  if (controller || attachmentUploads) return;
  const name = prompt("Project name:");
  if (name === null || !name.trim()) return;

  const response = await fetch("/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: name }),
  });
  const data = await response.json();

  if (!response.ok) {
    alert(data.detail);
    return;
  }

  // The server answers with the new project: { id, name }.
  await loadProjects();
  enterProject(data);
}

async function renameProject() {
  if (controller || attachmentUploads || currentProject === null) return;

  const name = prompt("Rename project:", currentProject.name);
  if (name === null || !name.trim()) return;

  const response = await fetch("/projects/" + currentProject.id, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: name }),
  });
  const data = await response.json();

  if (!response.ok) {
    alert(data.detail);
    return;
  }

  // Use the name the server saved (it may be trimmed or shortened).
  currentProject.name = data.name;
  showProjectMode();
}

async function deleteProject(project) {
  const count = project.chats + (project.chats === 1 ? " chat" : " chats");
  if (!confirm('Delete "' + project.name + '" and its ' + count + "?")) return;

  const response = await fetch("/projects/" + project.id, { method: "DELETE" });
  if (!response.ok) { alert(await responseError(response)); return; }
  loadProjects();
}

document.getElementById("new-project").addEventListener("click", createProject);
document.getElementById("leave-project").addEventListener("click", leaveProject);
document.getElementById("rename-project").addEventListener("click", renameProject);

// ---------- Start ----------

showProjectMode();
loadProjects();
