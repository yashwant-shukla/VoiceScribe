#!/usr/bin/env python3
"""
VoiceScribe Bootstrap — Dependency Checker & Installer (Offline Mode)

Runs before voicescribe.py to ensure all dependencies are present.
Uses only tkinter (built-in) so it can always show a UI, even when
every other package is missing.

In offline mode (launched from .app bundle), pip packages are installed
from bundled wheel files — no internet needed. Ollama binary and models
are also bundled.

Flow:
  1. Check all pip packages, bundled Ollama, and bundled models
  2. If everything is installed → launch voicescribe.py immediately
  3. If anything is missing → show a setup dialog with install buttons
  4. After installation → restart this script (os.execv)
"""

import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk

# ─── Dependency Registry ─────────────────────────────────────────────────────

PIP_PACKAGES = [
    {
        "name": "faster-whisper",
        "import_name": "faster_whisper",
        "min_version": "1.0.0",
        "critical": True,
        "description": "Speech recognition engine",
    },
    {
        "name": "sounddevice",
        "import_name": "sounddevice",
        "min_version": "0.4.6",
        "critical": True,
        "description": "Audio recording",
    },
    {
        "name": "numpy",
        "import_name": "numpy",
        "min_version": "1.24.0",
        "critical": True,
        "description": "Audio processing",
    },
    {
        "name": "pyperclip",
        "import_name": "pyperclip",
        "min_version": "1.8.2",
        "critical": True,
        "description": "Clipboard support",
    },
]

SYSTEM_DEPS = [
    {
        "name": "PortAudio",
        "brew_name": "portaudio",
        "critical": True,
        "description": "System audio library (required by sounddevice)",
        "check": "brew",
    },
    {
        "name": "Ollama",
        "critical": True,
        "description": "AI text polish engine (bundled)",
        "check": "bundled_binary",
    },
    {
        "name": "llama3.2 Model",
        "critical": True,
        "description": "AI model for text refinement (bundled)",
        "check": "bundled_model",
    },
    {
        "name": "Whisper Model",
        "critical": True,
        "description": "Speech recognition model (bundled)",
        "check": "bundled_whisper",
    },
]

# ─── Version Comparison ──────────────────────────────────────────────────────

def parse_version(v):
    """Parse version string into a comparable tuple."""
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)

# ─── Dependency Checker ──────────────────────────────────────────────────────

STATUS_INSTALLED = "installed"
STATUS_MISSING = "missing"
STATUS_OLD_VERSION = "old_version"
STATUS_INSTALLING = "installing"
STATUS_FAILED = "failed"


def check_pip_package(pkg):
    """Check if a pip package is installed with the right version."""
    try:
        version = importlib.metadata.version(pkg["name"])
        if parse_version(version) >= parse_version(pkg["min_version"]):
            return STATUS_INSTALLED, version
        else:
            return STATUS_OLD_VERSION, version
    except importlib.metadata.PackageNotFoundError:
        return STATUS_MISSING, None


def check_system_dep(dep):
    """Check if a system dependency is available."""
    check_type = dep["check"]

    if check_type == "brew":
        if not shutil.which("brew"):
            return False
        try:
            result = subprocess.run(
                ["brew", "list", dep["brew_name"]],
                capture_output=True, timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    elif check_type == "bundled_binary":
        # Check bundled Ollama binary
        bundled = os.environ.get("VOICESCRIBE_BUNDLED_OLLAMA", "")
        if bundled and os.path.isfile(bundled) and os.access(bundled, os.X_OK):
            return True
        # Fallback: check PATH and common locations
        if shutil.which("ollama"):
            return True
        for p in ["/opt/homebrew/bin/ollama", "/usr/local/bin/ollama"]:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return True
        return False

    elif check_type == "bundled_model":
        # Check bundled Ollama model (llama3.2)
        models_dir = os.environ.get("OLLAMA_MODELS", "")
        if not models_dir:
            return False
        blobs = os.path.join(models_dir, "blobs")
        manifests = os.path.join(models_dir, "manifests")
        return os.path.isdir(blobs) and os.path.isdir(manifests)

    elif check_type == "bundled_whisper":
        # Check bundled Whisper model cache
        hf_cache = os.environ.get("HF_HUB_CACHE", "")
        if not hf_cache or not os.path.isdir(hf_cache):
            return False
        # Check if there's at least one model directory
        for entry in os.listdir(hf_cache):
            if "whisper" in entry.lower() or "faster-whisper" in entry.lower():
                return True
        return False

    return False


def check_all():
    """Check all dependencies. Returns (pip_results, sys_results)."""
    pip_results = []
    for pkg in PIP_PACKAGES:
        status, version = check_pip_package(pkg)
        pip_results.append({**pkg, "status": status, "installed_version": version})

    sys_results = []
    for dep in SYSTEM_DEPS:
        installed = check_system_dep(dep)
        sys_results.append({
            **dep,
            "status": STATUS_INSTALLED if installed else STATUS_MISSING,
        })

    return pip_results, sys_results


def has_critical_missing(pip_results, sys_results):
    """Return True if any critical dependency is missing."""
    for r in pip_results:
        if r["critical"] and r["status"] != STATUS_INSTALLED:
            return True
    for r in sys_results:
        if r["critical"] and r["status"] != STATUS_INSTALLED:
            return True
    return False


def has_any_missing(pip_results, sys_results):
    """Return True if any dependency is missing."""
    for r in pip_results + sys_results:
        if r["status"] != STATUS_INSTALLED:
            return True
    return False


# ─── Installer ───────────────────────────────────────────────────────────────

def get_pip_executable():
    """Get the pip executable path (prefer venv)."""
    venv = os.environ.get("VOICESCRIBE_VENV", "")
    if venv and os.path.isfile(os.path.join(venv, "bin", "python")):
        return [os.path.join(venv, "bin", "python"), "-m", "pip"]
    return [sys.executable, "-m", "pip"]


def install_pip_package(pkg_name):
    """Install a pip package. Uses bundled wheels if available, else online."""
    pip_cmd = get_pip_executable()

    # Try bundled wheels first (offline)
    wheels_dir = os.environ.get("VOICESCRIBE_WHEELS", "")
    if wheels_dir and os.path.isdir(wheels_dir):
        cmd = pip_cmd + [
            "install", "--quiet",
            "--no-index",
            f"--find-links={wheels_dir}",
            pkg_name,
        ]
    else:
        # Fallback: online install
        cmd = pip_cmd + ["install", "--quiet", pkg_name]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return True, ""
        else:
            err = result.stderr.strip() or result.stdout.strip()
            return False, err[:300]
    except subprocess.TimeoutExpired:
        return False, "Installation timed out (5 minutes)"
    except Exception as e:
        return False, str(e)


def install_all_pip_from_wheels():
    """Install all packages from bundled wheels at once (faster)."""
    pip_cmd = get_pip_executable()
    wheels_dir = os.environ.get("VOICESCRIBE_WHEELS", "")

    if not wheels_dir or not os.path.isdir(wheels_dir):
        return False, "No bundled wheels directory found"

    # Get path to requirements.txt
    project_dir = os.environ.get(
        "VOICESCRIBE_PROJECT",
        os.path.dirname(os.path.abspath(__file__)),
    )
    req_file = os.path.join(project_dir, "requirements.txt")

    if os.path.isfile(req_file):
        cmd = pip_cmd + [
            "install", "--quiet",
            "--no-index",
            f"--find-links={wheels_dir}",
            "-r", req_file,
        ]
    else:
        # Install known packages individually
        cmd = pip_cmd + [
            "install", "--quiet",
            "--no-index",
            f"--find-links={wheels_dir}",
        ] + [p["name"] for p in PIP_PACKAGES]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return True, ""
        else:
            err = result.stderr.strip() or result.stdout.strip()
            return False, err[:500]
    except Exception as e:
        return False, str(e)


def install_system_dep(dep):
    """Install a system dependency via brew. Returns (success, error)."""
    if dep["check"] != "brew":
        return False, f"{dep['name']} must be bundled — cannot install at runtime"

    if not shutil.which("brew"):
        return False, "Homebrew not installed. Install from https://brew.sh"

    try:
        result = subprocess.run(
            ["brew", "install", dep["brew_name"]],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            return True, ""
        else:
            err = result.stderr.strip() or result.stdout.strip()
            return False, err[:300]
    except subprocess.TimeoutExpired:
        return False, "Installation timed out (5 minutes)"
    except Exception as e:
        return False, str(e)


# ─── UI: Dependency Setup Dialog ─────────────────────────────────────────────

DARK_BG = "#1e1e1e"
DARK_FG = "#e0e0e0"
DARK_SECONDARY = "#888888"
DARK_CARD = "#2a2a2a"
DARK_BORDER = "#3a3a3a"
DARK_ACCENT = "#007aff"
DARK_SUCCESS = "#30d158"
DARK_WARNING = "#ff9f0a"
DARK_ERROR = "#ff453a"

LIGHT_BG = "#f5f5f7"
LIGHT_FG = "#1d1d1f"
LIGHT_SECONDARY = "#6e6e73"
LIGHT_CARD = "#ffffff"
LIGHT_BORDER = "#d2d2d7"
LIGHT_ACCENT = "#007aff"
LIGHT_SUCCESS = "#34c759"
LIGHT_WARNING = "#ff9500"
LIGHT_ERROR = "#ff3b30"


def is_dark_mode():
    """Detect macOS dark mode."""
    if platform.system() != "Darwin":
        return False
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True, text=True,
        )
        return "dark" in result.stdout.strip().lower()
    except Exception:
        return False


class SetupDialog:
    """Dependency setup dialog using pure tkinter."""

    def __init__(self, pip_results, sys_results):
        self.pip_results = pip_results
        self.sys_results = sys_results
        self.dark = is_dark_mode()
        self.installing = False
        self.row_widgets = {}

        self.root = tk.Tk()
        self.root.title("VoiceScribe \u2014 Setup")
        self.root.geometry("520x580")
        self.root.minsize(450, 400)
        self.root.resizable(True, True)

        # Center on screen
        self.root.update_idletasks()
        w, h = 520, 580
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        self._setup_colors()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_quit)

    def _setup_colors(self):
        if self.dark:
            self.bg, self.fg = DARK_BG, DARK_FG
            self.secondary, self.card_bg = DARK_SECONDARY, DARK_CARD
            self.border, self.accent = DARK_BORDER, DARK_ACCENT
            self.success, self.warning, self.error = DARK_SUCCESS, DARK_WARNING, DARK_ERROR
        else:
            self.bg, self.fg = LIGHT_BG, LIGHT_FG
            self.secondary, self.card_bg = LIGHT_SECONDARY, LIGHT_CARD
            self.border, self.accent = LIGHT_BORDER, LIGHT_ACCENT
            self.success, self.warning, self.error = LIGHT_SUCCESS, LIGHT_WARNING, LIGHT_ERROR
        self.root.configure(bg=self.bg)

    def _build_ui(self):
        main = tk.Frame(self.root, bg=self.bg, padx=30, pady=20)
        main.pack(fill=tk.BOTH, expand=True)

        # Header
        tk.Label(
            main, text="VoiceScribe", font=("SF Pro Display", 22, "bold"),
            fg=self.fg, bg=self.bg,
        ).pack(anchor="w")

        tk.Label(
            main,
            text="Some dependencies need to be set up\nbefore VoiceScribe can start.",
            font=("SF Pro Text", 13), fg=self.secondary, bg=self.bg,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(4, 16))

        # Scrollable dependency list
        list_frame = tk.Frame(main, bg=self.bg)
        list_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(list_frame, bg=self.bg, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        self.deps_frame = tk.Frame(canvas, bg=self.bg)

        self.deps_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.deps_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Build sections
        self._build_section("Python Packages", self.pip_results)
        self._build_section("System & Bundled", self.sys_results)

        # Button bar
        btn_frame = tk.Frame(main, bg=self.bg)
        btn_frame.pack(fill=tk.X, pady=(16, 0))

        self.install_btn = tk.Button(
            btn_frame, text="Install All", font=("SF Pro Text", 13, "bold"),
            bg=self.accent, fg="white", activebackground=self.accent,
            activeforeground="white", relief=tk.FLAT, padx=20, pady=8,
            command=self._on_install_all, cursor="hand2",
        )
        self.install_btn.pack(side=tk.LEFT)

        self.quit_btn = tk.Button(
            btn_frame, text="Quit", font=("SF Pro Text", 12),
            bg=self.card_bg, fg=self.secondary, activebackground=self.border,
            relief=tk.FLAT, padx=16, pady=8,
            command=self._on_quit, cursor="hand2",
        )
        self.quit_btn.pack(side=tk.RIGHT)

        # Status bar
        self.status_label = tk.Label(
            main, text="", font=("SF Pro Text", 11),
            fg=self.secondary, bg=self.bg, anchor="w",
        )
        self.status_label.pack(fill=tk.X, pady=(8, 0))

    def _build_section(self, title, items):
        """Build a section of dependency rows."""
        if not items:
            return

        tk.Label(
            self.deps_frame, text=title, font=("SF Pro Text", 11, "bold"),
            fg=self.secondary, bg=self.bg,
        ).pack(anchor="w", pady=(12, 4))

        for item in items:
            self._build_row(item)

    def _build_row(self, item):
        """Build a single dependency row."""
        row = tk.Frame(self.deps_frame, bg=self.card_bg, padx=12, pady=8)
        row.pack(fill=tk.X, pady=2)

        if item["status"] == STATUS_INSTALLED:
            icon, icon_color = "\u2713", self.success
        else:
            icon, icon_color = "\u2717", self.error if item["critical"] else self.warning

        icon_label = tk.Label(
            row, text=icon, font=("SF Pro Text", 14),
            fg=icon_color, bg=self.card_bg, width=2,
        )
        icon_label.pack(side=tk.LEFT)

        info = tk.Frame(row, bg=self.card_bg)
        info.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        name_text = item["name"]
        if item.get("min_version"):
            name_text += f" \u2265{item['min_version']}"

        tk.Label(
            info, text=name_text, font=("SF Pro Text", 12, "bold"),
            fg=self.fg, bg=self.card_bg, anchor="w",
        ).pack(anchor="w")

        detail_text = item["description"]
        if item["status"] == STATUS_OLD_VERSION and item.get("installed_version"):
            detail_text += f" (installed: {item['installed_version']})"

        # Show "Bundled" badge for bundled deps that are present
        check_type = item.get("check", "")
        if check_type.startswith("bundled") and item["status"] == STATUS_INSTALLED:
            detail_text += " \u2022 Bundled"
        elif check_type.startswith("bundled") and item["status"] != STATUS_INSTALLED:
            detail_text += " \u2022 Missing from bundle — rebuild app"

        detail_label = tk.Label(
            info, text=detail_text, font=("SF Pro Text", 10),
            fg=self.secondary, bg=self.card_bg, anchor="w",
        )
        detail_label.pack(anchor="w")

        self.row_widgets[item["name"]] = {
            "icon": icon_label,
            "detail": detail_label,
            "row": row,
        }

    # ── Actions ──

    def _update_row_status(self, name, icon, icon_color, detail_text=None):
        def update():
            w = self.row_widgets.get(name)
            if not w:
                return
            w["icon"].config(text=icon, fg=icon_color)
            if detail_text is not None:
                w["detail"].config(text=detail_text)
        self.root.after(0, update)

    def _set_status(self, text):
        self.root.after(0, lambda: self.status_label.config(text=text))

    def _on_install_all(self):
        if self.installing:
            return
        self.installing = True
        self.install_btn.config(state=tk.DISABLED, text="Installing...")
        self.quit_btn.config(state=tk.DISABLED)

        def do_install():
            all_success = True

            # Install system deps first (only PortAudio is installable)
            for dep in self.sys_results:
                if dep["status"] != STATUS_INSTALLED and dep["check"] == "brew":
                    self._set_status(f"Installing {dep['name']}...")
                    self._update_row_status(dep["name"], "\u23f3", self.warning, "Installing...")

                    success, err = install_system_dep(dep)
                    if success:
                        self._update_row_status(dep["name"], "\u2713", self.success, dep["description"])
                        dep["status"] = STATUS_INSTALLED
                    else:
                        self._update_row_status(dep["name"], "\u2717", self.error, f"Failed: {err}")
                        dep["status"] = STATUS_FAILED
                        all_success = False

            # Try bulk install from wheels first (faster)
            missing_pip = [p for p in self.pip_results if p["status"] != STATUS_INSTALLED]
            if missing_pip:
                self._set_status("Installing Python packages from bundled wheels...")
                for p in missing_pip:
                    self._update_row_status(p["name"], "\u23f3", self.warning, "Installing...")

                success, err = install_all_pip_from_wheels()
                if success:
                    for p in missing_pip:
                        self._update_row_status(p["name"], "\u2713", self.success, p["description"])
                        p["status"] = STATUS_INSTALLED
                else:
                    # Fallback: install one by one
                    self._set_status("Bulk install failed — installing packages individually...")
                    for pkg in missing_pip:
                        self._set_status(f"Installing {pkg['name']}...")
                        success, err = install_pip_package(pkg["name"])
                        if success:
                            self._update_row_status(pkg["name"], "\u2713", self.success, pkg["description"])
                            pkg["status"] = STATUS_INSTALLED
                        else:
                            self._update_row_status(pkg["name"], "\u2717", self.error, f"Failed: {err}")
                            pkg["status"] = STATUS_FAILED
                            all_success = False

            # Check for bundled deps that can't be installed (only shown as errors)
            for dep in self.sys_results:
                if dep["status"] != STATUS_INSTALLED and dep["check"].startswith("bundled"):
                    all_success = False

            self.installing = False

            if all_success or not has_critical_missing(self.pip_results, self.sys_results):
                self._set_status("Setup complete! Restarting...")
                self.root.after(1500, self._restart)
            else:
                self._set_status("Some items could not be installed. See details above.")
                self.root.after(0, lambda: self.install_btn.config(
                    state=tk.NORMAL, text="Retry"
                ))
                self.root.after(0, lambda: self.quit_btn.config(state=tk.NORMAL))

        threading.Thread(target=do_install, daemon=True).start()

    def _on_quit(self):
        self.root.destroy()
        sys.exit(0)

    def _restart(self):
        self.root.destroy()
        restart_bootstrap()

    def run(self):
        self.root.mainloop()


# ─── Bootstrap Orchestrator ──────────────────────────────────────────────────

def launch_main_app():
    """Import and run voicescribe.main()."""
    project_dir = os.environ.get(
        "VOICESCRIBE_PROJECT",
        os.path.dirname(os.path.abspath(__file__)),
    )
    os.chdir(project_dir)

    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)

    import voicescribe
    voicescribe.main()


def restart_bootstrap():
    """Re-execute this bootstrap script to recheck dependencies."""
    count = int(os.environ.get("VOICESCRIBE_RESTART_COUNT", "0"))
    if count >= 3:
        print("Too many restart attempts. Please check your setup manually.")
        sys.exit(1)

    os.environ["VOICESCRIBE_RESTART_COUNT"] = str(count + 1)
    os.execv(sys.executable, [sys.executable] + sys.argv)


def main():
    """Main bootstrap entry point."""
    pip_results, sys_results = check_all()

    if not has_any_missing(pip_results, sys_results):
        launch_main_app()
        return

    # If only non-critical things are missing, launch anyway
    if not has_critical_missing(pip_results, sys_results):
        launch_main_app()
        return

    # Critical deps missing — show setup dialog
    dialog = SetupDialog(pip_results, sys_results)
    dialog.run()


if __name__ == "__main__":
    main()
