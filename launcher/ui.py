"""The launcher: installs Cerberus once, then only opens it.

Updates happen inside the app (Settings → Updates). When the app is already
installed, the launcher opens it without showing a window, so the menu entry
keeps working after updates. Downloads and disk work run off the UI thread.
"""

import queue
import sys
import threading
import time
import webbrowser
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox

from launcher.manager import (LauncherError, Manager, app_data_directory, check_writable, forget_root,
                              latest_release, root_in, save_root, saved_root)
from launcher.presentation import PLATFORM_LABELS, progress_label, size_label
from launcher.shortcuts import register, unregister

HELP_URL = "https://github.com/23lambi/Cerberus-ai/blob/main/docs/launcher.md"

# The app's own colors (static/style.css).
BACKGROUND = "#17181d"
CARD = "#1f2128"
BORDER = "#2c2f38"
TEXT = "#e6e8ed"
MUTED = "#9aa0ad"
FAINT = "#5d6270"
ACCENT = "#e8707e"
ACCENT_HOVER = "#f28996"
WARN = "#f0a35e"


def font_family(root):
    """A clean sans-serif; Tk's default on Linux is often a dated bitmap font."""
    if sys.platform == "darwin":
        return tkfont.nametofont("TkDefaultFont", root).actual("family")  # the system font
    available = {name.lower(): name for name in tkfont.families(root)}
    for name in ("Segoe UI", "Inter", "Noto Sans", "Cantarell", "Ubuntu", "DejaVu Sans", "Liberation Sans"):
        if name.lower() in available:
            return available[name.lower()]
    return tkfont.nametofont("TkDefaultFont", root).actual("family")


def resource(name):
    base = Path(__file__).resolve().parents[1]  # the bundle when frozen, the project otherwise
    for path in (base / name, base / "static" / name):
        if path.is_file():
            return path
    return None


def rounded(canvas, x1, y1, x2, y2, radius, **options):
    radius = max(0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius, x2, y2 - radius, x2, y2,
              x2 - radius, y2, x1 + radius, y2, x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1]
    return canvas.create_polygon(points, smooth=True, **options)


class Button(tk.Canvas):
    """A flat, rounded button; Tk's own buttons look dated on every system."""

    STYLES = {
        "primary": {"fill": ACCENT, "hover": ACCENT_HOVER, "text": BACKGROUND, "outline": ""},
        "quiet": {"fill": CARD, "hover": "#2a2d36", "text": TEXT, "outline": BORDER},
    }

    def __init__(self, parent, text, command, style="primary", height=44, font=None, width=None):
        super().__init__(parent, height=height, bg=parent["bg"], highlightthickness=0, bd=0,
                         cursor="hand2", takefocus=1, **({"width": width} if width else {}))
        self.text, self.command, self.style, self.font = text, command, style, font
        self.enabled, self.hover = True, False
        self.bind("<Configure>", lambda _: self.draw())
        self.bind("<Enter>", lambda _: self.set_hover(True))
        self.bind("<Leave>", lambda _: self.set_hover(False))
        self.bind("<ButtonRelease-1>", lambda event: self.click() if 0 <= event.x <= self.winfo_width()
                  and 0 <= event.y <= self.winfo_height() else None)
        self.bind("<Return>", lambda _: self.click())
        self.bind("<space>", lambda _: self.click())
        self.bind("<FocusIn>", lambda _: self.draw())
        self.bind("<FocusOut>", lambda _: self.draw())

    def configure_button(self, text=None, enabled=None, style=None, command=None):
        if text is not None:
            self.text = text
        if enabled is not None:
            self.enabled = enabled
            self.configure(cursor="hand2" if enabled else "arrow")
        if style is not None:
            self.style = style
        if command is not None:
            self.command = command
        self.draw()

    def set_hover(self, hover):
        self.hover = hover
        self.draw()

    def click(self):
        if self.enabled:
            self.command()

    def draw(self):
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        if width < 4:
            return
        style = self.STYLES[self.style]
        fill = style["hover"] if self.hover and self.enabled else style["fill"]
        text = style["text"]
        if not self.enabled:
            fill, text = ("#3a2a30" if self.style == "primary" else CARD), FAINT
        outline = TEXT if self.focus_get() is self and self.enabled else style["outline"]
        rounded(self, 1, 1, width - 1, height - 1, 10, fill=fill, outline=outline, width=1)
        self.create_text(width / 2, height / 2, text=self.text, fill=text, font=self.font)


class Progress(tk.Canvas):
    """A thin rounded bar; moving stripe when the total is unknown."""

    def __init__(self, parent):
        super().__init__(parent, height=6, bg=parent["bg"], highlightthickness=0, bd=0)
        self.fraction, self.moving, self.offset = 0.0, False, 0.0
        self.bind("<Configure>", lambda _: self.draw())

    def set(self, fraction):
        self.moving = False
        self.fraction = max(0.0, min(1.0, fraction))
        self.draw()

    def spin(self):
        if not self.moving:
            self.moving = True
            self.animate()

    def animate(self):
        if self.moving:
            self.offset = (self.offset + 0.02) % 1.3
            self.draw()
            self.after(16, self.animate)

    def draw(self):
        self.delete("all")
        if not self.moving and not self.fraction:
            return  # no empty track before anything happens
        width = self.winfo_width()
        rounded(self, 0, 0, width, 6, 3, fill=BORDER, outline="")
        if self.moving:
            start = (self.offset - 0.3) * width
            rounded(self, max(0, start), 0, min(width, start + 0.3 * width), 6, 3, fill=ACCENT, outline="")
        elif self.fraction:
            rounded(self, 0, 0, max(6, width * self.fraction), 6, 3, fill=ACCENT, outline="")


class Window:
    def __init__(self, root, manager, problem=None):
        self.root, self.manager = root, manager
        self.install_root = manager.root
        self.release = None
        self.busy = False
        self.cancel = threading.Event()
        self.events = queue.Queue()
        family = font_family(root)
        self.fonts = {size: (family, size) for size in (10, 11, 12)}
        self.fonts["title"] = (family, 22, "bold")
        self.fonts["button"] = (family, 12, "bold")
        self.fonts["caption"] = (family, 9, "bold")

        root.title("Install Cerberus")
        root.configure(bg=BACKGROUND)
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.close)
        logo = resource("cerberus.png")
        if logo:
            self.icon = tk.PhotoImage(file=str(logo))
            self.logo = self.icon.subsample(8)  # 512 px → 64 px
            root.iconphoto(True, self.icon.subsample(4))

        body = tk.Frame(root, bg=BACKGROUND, padx=36, pady=32)
        body.pack(fill="both", expand=True)
        if logo:
            tk.Label(body, image=self.logo, bg=BACKGROUND).pack(anchor="w")
        self.label(body, "Cerberus", self.fonts["title"], TEXT).pack(anchor="w", pady=(14, 2))
        self.label(body, "Chat, documents and research with local or cloud AI.",
                   self.fonts[11], MUTED).pack(anchor="w")

        card = tk.Frame(body, bg=CARD, highlightthickness=1, highlightbackground=BORDER, padx=16, pady=14)
        card.pack(fill="x", pady=(24, 0))
        self.label(card, "INSTALL LOCATION", self.fonts["caption"], FAINT, CARD).pack(anchor="w")
        self.path = self.label(card, "", self.fonts[11], TEXT, CARD)
        self.path.configure(anchor="w", justify="left", wraplength=410)
        self.path.pack(fill="x", pady=(6, 0))
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", pady=(10, 0))
        self.change_button = Button(row, "Change…", self.choose_folder, "quiet", 32, self.fonts[10], width=92)
        self.change_button.pack(side="right")
        self.details = self.label(row, PLATFORM_LABELS[manager.target] + " · Finding the latest version…",
                                  self.fonts[10], MUTED, CARD)
        self.details.pack(side="left")

        self.progress = Progress(body)
        self.progress.pack(fill="x", pady=(22, 0))
        self.status = self.label(body, "", self.fonts[10], MUTED)
        self.status.configure(anchor="w", justify="left", wraplength=448)
        self.status.pack(fill="x", pady=(8, 0))

        self.main_button = Button(body, "Install Cerberus", self.install, "primary", 46, self.fonts["button"])
        self.main_button.pack(fill="x", pady=(16, 0))

        footer = tk.Frame(body, bg=BACKGROUND)
        footer.pack(fill="x", pady=(16, 0))
        self.label(footer, "Your chats and settings are stored separately.", self.fonts[10], FAINT).pack(side="left")
        help_link = self.label(footer, "Help", self.fonts[10], MUTED)
        help_link.configure(cursor="hand2")
        help_link.bind("<Button-1>", lambda _: webbrowser.open(HELP_URL))
        help_link.pack(side="right")

        self.show_path()
        if problem:
            self.say(problem + " Install again to repair it; your data is kept.", WARN)
        root.update_idletasks()
        width, height = 520, root.winfo_reqheight()
        x = (root.winfo_screenwidth() - width) // 2
        y = (root.winfo_screenheight() - height) // 3
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.after(100, self.poll)
        self.find_release()

    @staticmethod
    def label(parent, text, font, color, background=BACKGROUND):
        return tk.Label(parent, text=text, bg=background, fg=color, font=font)

    def say(self, text, color=MUTED):
        self.status.configure(text=text, fg=color)

    def show_path(self):
        path, home = self.install_root, Path.home()
        self.path.configure(text=str(Path("~") / path.relative_to(home)) if path.is_relative_to(home) else str(path))

    def refresh(self):
        self.change_button.configure_button(enabled=not self.busy)
        if self.busy:
            self.main_button.configure_button("Cancel", True, "quiet", self.cancel.set)
        elif self.release:
            self.main_button.configure_button("Install Cerberus", True, "primary", self.install)
        else:
            self.main_button.configure_button("Try again", True, "primary", self.find_release)

    def run(self, kind, function):
        def worker():
            try:
                self.events.put((kind, function()))
            except Exception as error:  # shown to the user, never a crash
                self.events.put(("error", str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def find_release(self):
        self.main_button.configure_button("Install Cerberus", False, "primary")
        self.say("Checking for the latest version…")
        self.run("release", lambda: latest_release(self.manager.target))

    def choose_folder(self):
        start = self.install_root.parent if self.install_root.parent.is_dir() else Path.home()
        chosen = filedialog.askdirectory(parent=self.root, title="Choose where to install Cerberus",
                                         initialdir=str(start), mustexist=False)
        if chosen:
            self.install_root = root_in(chosen)
            self.show_path()

    def install(self):
        if self.busy or not self.release:
            return
        self.busy = True
        self.cancel.clear()
        self.refresh()
        self.progress.spin()
        self.say("Preparing…")
        release, root = self.release, self.install_root

        def progress(text, done, total):
            self.events.put(("progress", (text, done, total)))

        def task():
            check_writable(root)
            manager = Manager(root, self.manager.target)
            manager.install(release, progress, self.cancel.is_set)
            self.manager = manager
            save_root(root)
            try:
                register(root)
            except Exception:
                pass  # The launcher still opens the app; only the menu entry is missing.
            progress("Opening Cerberus", 0, 0)
            manager.launch()
            return release["version"]
        self.run("installed", task)

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "release":
                    self.release = value
                    self.details.configure(text=" · ".join([PLATFORM_LABELS[self.manager.target], value["version"],
                                                            size_label(value["size"]) + " download"]))
                    if self.status.cget("fg") != WARN:
                        self.say("Ready to install. AI models are set up later, inside the app.")
                    self.refresh()
                elif kind == "progress":
                    text, done, total = value
                    if total:
                        self.progress.set(done / total)
                    else:
                        self.progress.spin()
                    self.say(text + " · " + progress_label(done, total) if total else text + "…")
                elif kind == "installed":
                    self.progress.set(1)
                    self.say(f"Cerberus {value} is installed. Opening it now…", TEXT)
                    self.main_button.configure_button("Opening Cerberus…", False, "primary")
                    self.change_button.configure_button(enabled=False)
                    self.root.after(1800, self.root.destroy)
                    return
                elif kind == "error":
                    self.busy = False
                    self.progress.set(0)
                    self.say(value, WARN)
                    self.refresh()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def close(self):
        if self.busy:
            self.cancel.set()
            self.say("Stopping the download…")
            return
        self.root.destroy()


def enable_sharp_text():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def message(kind, title, text):
    window = tk.Tk()
    window.withdraw()
    try:
        return getattr(messagebox, kind)(title, text, parent=window)
    finally:
        window.destroy()


def uninstall():
    """Started by the app (Settings → Uninstall) after it closes itself."""
    manager = Manager(saved_root())
    data = app_data_directory()
    if not message("askyesno", "Uninstall Cerberus",
                   "Remove the Cerberus app from this computer?\n\n"
                   f"Your chats, settings, API keys and models stay in:\n{data}"):
        return
    deadline = time.monotonic() + 30
    while manager.running() and time.monotonic() < deadline:
        time.sleep(0.5)
    try:
        manager.uninstall()
        unregister(manager.root)
        for name in ("installation.json", "app.log", "operation.lock"):
            (manager.root / name).unlink(missing_ok=True)
        try:
            manager.root.rmdir()
        except OSError:
            pass  # On Windows the launcher itself is still in it.
        forget_root()
    except (LauncherError, OSError) as error:
        message("showerror", "Uninstall Cerberus", str(error))
        return
    message("showinfo", "Uninstall Cerberus", f"Cerberus was removed. Your data is still in:\n{data}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    enable_sharp_text()
    if "--uninstall" in argv:
        uninstall()
        return
    try:
        manager = Manager(saved_root())
    except LauncherError as error:
        message("showerror", "Cerberus", str(error))
        return
    problem = None
    try:
        state = manager.state()
    except LauncherError as error:
        state, problem = None, str(error)
    if state:
        try:
            manager.launch()
            return  # Installed: the launcher's only job is to open the app.
        except LauncherError as error:
            if manager.running():
                message("showinfo", "Cerberus", "Cerberus is already open.")
                return
            problem = str(error)
    root = tk.Tk()
    Window(root, manager, problem)
    root.mainloop()
