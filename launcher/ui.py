"""A native launcher window; downloads and disk work run off the UI thread."""

import queue
import threading
import webbrowser
import tkinter as tk
from tkinter import messagebox, ttk

from launcher.manager import LauncherError, Manager, app_data_directory, latest_release
from launcher.shortcuts import register
from launcher.presentation import PLATFORM_LABELS, install_action, ready_message


class Window:
    def __init__(self, root, manager=None):
        self.root = root
        self.manager = manager or Manager()
        self.release = None
        self.busy = False
        self.checking = False
        self.last_exit = None
        self.cancel = threading.Event()
        self.events = queue.Queue()
        root.title("Cerberus Launcher")
        root.geometry("620x560")
        root.minsize(580, 540)
        root.configure(bg="#17181d")
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TProgressbar", troughcolor="#272a33", background="#e8707e", borderwidth=0)
        style.configure("TButton", font=("TkDefaultFont", 11), padding=(14, 9), background="#272a33", foreground="#e6e8ed")
        style.map("TButton", background=[("active", "#3b3f4b")], foreground=[("disabled", "#777e8c")])
        style.configure("Primary.TButton", background="#e8707e", foreground="#17181d")
        style.map("Primary.TButton", background=[("active", "#f28996"), ("disabled", "#3b3f4b")])

        body = tk.Frame(root, bg="#17181d", padx=30, pady=26)
        body.pack(fill="both", expand=True)
        self.label(body, "CERBERUS", size=24, color="#e6e8ed", bold=True).pack(anchor="w")
        self.label(body, "Install and update Cerberus. No Python or Git setup needed.", size=11).pack(anchor="w", pady=(5, 24))
        self.installed = self.label(body, "Checking installation…", size=13, color="#e6e8ed")
        self.installed.pack(anchor="w")
        self.latest = self.label(body, PLATFORM_LABELS[self.manager.target] + " · Checking updates…", size=11)
        self.latest.pack(anchor="w", pady=(6, 16))
        self.progress = ttk.Progressbar(body, mode="determinate")
        self.progress.pack(fill="x", pady=(0, 12))
        self.status = self.label(body, "", size=11)
        self.status.configure(wraplength=550, justify="left")
        self.status.pack(anchor="w", fill="x")
        self.actions = tk.Frame(body, bg="#17181d")
        self.actions.pack(fill="x", pady=(22, 10))
        self.install_button = ttk.Button(self.actions, text="Install Cerberus", style="Primary.TButton", command=self.install)
        self.install_button.pack(side="left")
        self.launch_button = ttk.Button(self.actions, text="Open Cerberus", command=self.launch)
        self.launch_button.pack(side="left", padx=8)
        self.cancel_button = ttk.Button(self.actions, text="Cancel", command=self.cancel.set)
        self.secondary = tk.Frame(body, bg="#17181d")
        self.secondary.pack(fill="x", pady=4)
        self.check_button = ttk.Button(self.secondary, text="Check updates", command=self.check)
        self.check_button.pack(side="left")
        self.repair_button = ttk.Button(self.secondary, text="Repair", command=lambda: self.install(repair=True))
        self.repair_button.pack(side="left", padx=8)
        self.uninstall_button = ttk.Button(self.secondary, text="Uninstall app", command=self.uninstall)
        self.uninstall_button.pack(side="left")
        self.help_button = ttk.Button(self.secondary, text="Help", command=lambda: webbrowser.open(
            "https://github.com/23lambi/Cerberus-ai/blob/main/docs/launcher.md"))
        self.help_button.pack(side="left", padx=(8, 0))
        self.label(body, "Your chats, API keys and models are kept separately.", size=10).pack(anchor="w", pady=(18, 0))
        root.after(100, self.poll)
        self.refresh()
        self.check()

    @staticmethod
    def label(parent, text, size=11, color="#9aa0ad", bold=False):
        return tk.Label(parent, text=text, bg="#17181d", fg=color,
                        font=("TkDefaultFont", size, "bold" if bold else "normal"))

    def refresh(self):
        try:
            state = self.manager.state()
        except LauncherError as error:
            state = None
            self.status.configure(text=str(error))
        self.installed.configure(text="Cerberus " + state["version"] + " is installed" if state else "Ready for your first install")
        action, available = install_action(state["version"] if state else None,
                                           self.release["version"] if self.release else None)
        self.install_button.configure(text=action)
        self.launch_button.configure(state="normal" if state and not self.busy else "disabled")
        self.repair_button.configure(state="normal" if self.release and state and not self.busy else "disabled")
        self.uninstall_button.configure(state="normal" if state and not self.busy else "disabled")
        self.install_button.configure(state="normal" if available and not self.busy else "disabled")
        self.check_button.configure(state="disabled" if self.busy or self.checking else "normal")

    def work(self, function, checking=False):
        if self.busy or (checking and self.checking):
            return
        if checking:
            self.checking = True
        else:
            self.busy = True
        self.cancel.clear()
        self.refresh()
        def worker():
            try:
                self.events.put(("checked" if checking else "done", function()))
            except Exception as error:
                self.events.put(("check-error" if checking else "error", str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def check(self):
        self.status.configure(text="Checking for updates…")
        def task():
            release = latest_release(self.manager.target)
            self.events.put(("release", release))
            state = self.manager.state()
            return ready_message(state["version"] if state else None, release["version"])
        self.work(task, checking=True)

    def install(self, repair=False):
        if not self.release or self.busy:
            return
        if repair and not messagebox.askyesno("Repair Cerberus", "Download and reinstall the latest application? Your data will be kept."):
            return
        self.cancel_button.pack(side="right")
        def progress(text, done, total):
            self.events.put(("progress", (text, done, total)))
        def task():
            self.manager.install(self.release, progress, self.cancel.is_set)
            try:
                register(self.manager.root)
            except Exception:
                return "Cerberus is installed. Choose Open Cerberus to get started. A menu shortcut could not be created; keep this launcher to open it later."
            return "Cerberus is installed. Choose Open Cerberus to get started."
        self.work(task)

    def launch(self):
        self.work(lambda: self.manager.launch() and "Cerberus is starting. Its log is in " + str(self.manager.root / "app.log"))

    def uninstall(self):
        if not messagebox.askyesno("Uninstall Cerberus", "Remove the installed app? Your chats, settings, API keys and models will be kept."):
            return
        def task():
            self.manager.uninstall()
            return "Application removed. Your data is still in " + str(app_data_directory())
        self.work(task)

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "release":
                    self.release = value
                    self.latest.configure(text=PLATFORM_LABELS[self.manager.target] + " · Latest " + value["version"])
                elif kind == "progress":
                    text, done, total = value
                    self.status.configure(text=text + (f" · {done / total:.0%}" if total else ""))
                    if total:
                        self.progress.stop()
                        self.progress.configure(mode="determinate", maximum=total, value=done)
                    else:
                        self.progress.configure(mode="indeterminate")
                        self.progress.start()
                elif kind in ("checked", "check-error"):
                    self.checking = False
                    if not self.busy:
                        if kind == "check-error":
                            self.latest.configure(text=PLATFORM_LABELS[self.manager.target] + " · Updates unavailable")
                            try:
                                installed = self.manager.state()
                            except LauncherError:
                                installed = None
                            if installed:
                                value += " You can still open your installed app."
                        self.status.configure(text=value)
                    self.refresh()
                else:
                    self.busy = False
                    self.cancel_button.pack_forget()
                    self.progress.stop()
                    self.progress.configure(mode="determinate", maximum=1, value=0)
                    self.status.configure(text=value)
                    self.refresh()
        except queue.Empty:
            pass
        process = self.manager.process
        if process is not None and process.poll() is not None and self.last_exit != process.pid and not self.busy:
            self.last_exit = process.pid
            self.status.configure(text="Cerberus closed." if process.returncode == 0 else
                                  "Cerberus could not stay open. See " + str(self.manager.root / "app.log"))
        self.root.after(100, self.poll)

    def close(self):
        if self.busy:
            self.cancel.set()
            self.status.configure(text="Finishing the current operation. You can close the launcher when it completes.")
            return
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        Window(root)
    except (LauncherError, OSError) as error:
        messagebox.showerror("Cerberus Launcher", str(error))
        root.destroy()
        return
    root.mainloop()
