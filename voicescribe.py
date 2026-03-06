"""
VoiceScribe v2 — Free, cross-platform voice-to-text transcription tool.
Uses local Whisper model for accurate, private transcription.
Bundled Ollama + llama3.2 for AI-powered text polishing (fully offline).
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import sounddevice as sd
import numpy as np
import wave
import tempfile
import os
import sys
import threading
import time
import platform
import json
import glob
import atexit
import signal
import logging
import math
import shutil
import subprocess
import urllib.request
import urllib.error

try:
    import pyperclip
    CLIPBOARD_AVAILABLE = True
except ImportError:
    CLIPBOARD_AVAILABLE = False

from faster_whisper import WhisperModel


# ─── Constants ────────────────────────────────────────────────────────────────

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "float32"

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "llama3.2"

MAX_RECORDING_SECONDS = 600
MAX_HISTORY_ITEMS = 50
MAX_HISTORY_CHARS = 100_000
TEMP_FILE_PREFIX = "voicescribe_"

APP_VERSION = "2.0.0"

PRIVACY_NOTICE = """VoiceScribe — Privacy & Data Handling

Before you start, here's what this app does with your data:

\u2022 Microphone audio: Captured only while you hold Record. Saved to a temporary file for transcription, then immediately deleted. Never sent anywhere.

\u2022 Transcription: Processed locally on your machine using the bundled Whisper model. No data leaves your computer.

\u2022 AI Polish: Text is refined by a bundled local AI model (Ollama + llama3.2) running entirely on your machine (localhost:11434). Nothing goes to the internet.

\u2022 Clipboard: Transcriptions are auto-copied to your clipboard. Clear the clipboard manually if needed.

\u2022 No data is stored on disk. All history is in-memory and lost when you close the app.

\u2022 No analytics, no telemetry, no network calls. Everything runs 100% offline.
"""

REFINE_SYSTEM_PROMPT = """You are a prompt refinement assistant. Your job is to take raw voice transcriptions and turn them into clear, well-structured prompts ready to paste into an AI assistant like Claude or ChatGPT.

Rules:
1. Remove filler words (um, uh, like, you know, basically, so yeah, etc.)
2. Fix grammar and sentence structure while preserving the speaker's intent exactly
3. Organize the content logically — if the speaker mentioned multiple things, use clear sections
4. Keep all technical details, names, code references, and specifics intact
5. Do NOT add information the speaker didn't mention
6. Do NOT answer the prompt — just clean it up
7. If the speaker is describing a bug, structure it as: what happened, what was expected, relevant context
8. If the speaker is asking for code, structure it as: what they want, constraints, language/framework
9. If it's a general question or request, just make it clear and concise
10. Output ONLY the refined prompt — no preamble, no explanation, no quotes around it"""

IS_MAC = platform.system() == "Darwin"

# Friendly labels for Whisper model sizes
WHISPER_LABELS = {
    "tiny":   ("Fast",     "Quick results, lower accuracy"),
    "base":   ("Balanced", "Good speed and accuracy"),
    "small":  ("High",     "Better accuracy, takes longer"),
    "medium": ("Best",     "Highest accuracy, slowest"),
}
WHISPER_SIZES = list(WHISPER_LABELS.keys())
WHISPER_DISPLAY_NAMES = [WHISPER_LABELS[s][0] for s in WHISPER_SIZES]

LANGUAGES = {
    "Auto-detect": None,
    "English": "en",
    "Hindi": "hi",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Japanese": "ja",
    "Chinese": "zh",
    "Korean": "ko",
    "Portuguese": "pt",
    "Italian": "it",
    "Dutch": "nl",
    "Russian": "ru",
    "Arabic": "ar",
    "Turkish": "tr",
}

FONT_FAMILY = "SF Pro" if IS_MAC else "Helvetica Neue"
FONT_FALLBACK = ("Helvetica Neue", "Helvetica", "Arial")


# ─── Theme System ─────────────────────────────────────────────────────────────

LIGHT_THEME = {
    "bg":              "#f5f5f7",
    "surface":         "#ffffff",
    "text":            "#1d1d1f",
    "text_secondary":  "#6e6e73",
    "accent":          "#007aff",
    "accent_hover":    "#0063d1",
    "record":          "#ff3b30",
    "record_hover":    "#d42e25",
    "success":         "#34c759",
    "warning":         "#ff9500",
    "border":          "#d2d2d7",
    "border_light":    "#e5e5ea",
    "selection":       "#b4d8fd",
    "polish":          "#5856d6",
    "polish_hover":    "#4643b5",
    "pause":           "#ff9500",
    "pause_hover":     "#e08600",
    "stop":            "#6e6e73",
    "stop_hover":      "#555558",
    "settings_bg":     "#eeeef0",
    "tooltip_bg":      "#333336",
    "tooltip_fg":      "#ffffff",
}

DARK_THEME = {
    "bg":              "#1c1c1e",
    "surface":         "#2c2c2e",
    "text":            "#f5f5f7",
    "text_secondary":  "#98989d",
    "accent":          "#0a84ff",
    "accent_hover":    "#409cff",
    "record":          "#ff453a",
    "record_hover":    "#ff6961",
    "success":         "#30d158",
    "warning":         "#ff9f0a",
    "border":          "#38383a",
    "border_light":    "#48484a",
    "selection":       "#0a3d6b",
    "polish":          "#5e5ce6",
    "polish_hover":    "#7a78f0",
    "pause":           "#ff9f0a",
    "pause_hover":     "#ffb340",
    "stop":            "#98989d",
    "stop_hover":      "#b0b0b5",
    "settings_bg":     "#2c2c2e",
    "tooltip_bg":      "#f5f5f7",
    "tooltip_fg":      "#1d1d1f",
}


class ThemeManager:
    """Manages light/dark/system theme switching."""

    def __init__(self):
        self.mode = "system"  # "light", "dark", "system"
        self._resolved = self._detect_system()

    def _detect_system(self):
        """Detect macOS dark mode, fallback to light."""
        if IS_MAC:
            try:
                result = subprocess.run(
                    ["defaults", "read", "-g", "AppleInterfaceStyle"],
                    capture_output=True, text=True, timeout=2,
                )
                if "Dark" in result.stdout:
                    return "dark"
            except Exception:
                pass
        return "light"

    def set_mode(self, mode):
        self.mode = mode
        if mode == "system":
            self._resolved = self._detect_system()
        else:
            self._resolved = mode

    @property
    def colors(self):
        return DARK_THEME if self._resolved == "dark" else LIGHT_THEME

    @property
    def is_dark(self):
        return self._resolved == "dark"

    def c(self, key):
        """Shorthand for getting a color."""
        return self.colors[key]


# ─── Ollama Manager ──────────────────────────────────────────────────────────

class OllamaManager:
    """Manages Ollama: HTTP client + subprocess lifecycle + health checks."""

    # Common install locations for Ollama on macOS/Linux
    OLLAMA_SEARCH_PATHS = [
        "/opt/homebrew/bin/ollama",        # Homebrew (Apple Silicon)
        "/usr/local/bin/ollama",           # Homebrew (Intel) / manual install
        "/usr/bin/ollama",                 # System install
        os.path.expanduser("~/.ollama/bin/ollama"),  # User install
    ]

    def __init__(self, base_url=OLLAMA_BASE_URL, bundled_path=None):
        self.base_url = base_url
        self.process = None
        self.we_started_it = False
        self.is_running = False
        self.models = []
        self.logger = logging.getLogger("OllamaManager")
        self._bundled_path = bundled_path  # Path to bundled Ollama binary (from .app)
        self._ollama_path = None  # Cached resolved path to ollama binary

    def find_ollama(self):
        """Find the ollama binary: bundled path → PATH → common install locations."""
        if self._ollama_path and os.path.isfile(self._ollama_path):
            return self._ollama_path

        # Highest priority: bundled binary from .app bundle
        if self._bundled_path and os.path.isfile(self._bundled_path) and os.access(self._bundled_path, os.X_OK):
            self._ollama_path = self._bundled_path
            self.logger.info(f"Using bundled Ollama: {self._bundled_path}")
            return self._bundled_path

        # Next: check PATH
        path = shutil.which("ollama")
        if path:
            self._ollama_path = path
            self.logger.info(f"Found ollama on PATH: {path}")
            return path

        # Fallback: check common install locations
        for candidate in self.OLLAMA_SEARCH_PATHS:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                self._ollama_path = candidate
                self.logger.info(f"Found ollama at: {candidate}")
                return candidate

        self.logger.warning("Ollama binary not found in bundle, PATH, or common locations")
        return None

    # ── HTTP Client ──

    def check_health(self):
        """Ping Ollama to see if it's alive."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                self.is_running = resp.status == 200
                if self.is_running:
                    raw = resp.read().decode()
                    self.logger.info(f"Ollama /api/tags raw response: {raw[:500]}")
                    data = json.loads(raw)
                    # Ollama returns {"models": [...]} — parse model names
                    model_list = data.get("models", [])
                    self.logger.info(f"Ollama returned {len(model_list)} model(s), keys in response: {list(data.keys())}")
                    self.models = [m.get("name", m.get("model", "")) for m in model_list if isinstance(m, dict)]
                    if not self.models:
                        self.logger.info(f"Ollama running but 0 models found. Full response: {data}")
        except Exception as e:
            self.logger.info(f"Ollama health check failed: {e}")
            self.is_running = False
            self.models = []
        return self.is_running

    def generate(self, model, prompt, system_prompt=""):
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
            return data.get("response", "").strip()

    # ── Subprocess Management ──

    def start(self):
        """Start Ollama server if not already running."""
        if self.check_health():
            self.we_started_it = False
            return True

        ollama_path = self.find_ollama()
        if not ollama_path:
            return False

        try:
            self.process = subprocess.Popen(
                [ollama_path, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid if hasattr(os, "setsid") else None,
            )
            self.we_started_it = True
            self.logger.info(f"Started Ollama (PID {self.process.pid})")

            # Phase 1: Wait for server to come up (up to 10s)
            server_up = False
            for _ in range(20):
                time.sleep(0.5)
                if self.check_health():
                    server_up = True
                    break

            if not server_up:
                self.logger.warning("Ollama started but server never responded")
                return False

            # Phase 2: Server is up — wait for models to be indexed (up to 10s more)
            if not self.models:
                self.logger.info("Server up but no models yet — waiting for indexing...")
                for _ in range(20):
                    time.sleep(0.5)
                    self.check_health()
                    if self.models:
                        self.logger.info(f"Models found: {self.models}")
                        break

            return True
        except Exception as e:
            self.logger.error(f"Failed to start Ollama: {e}")
            return False

    def stop(self):
        """Stop Ollama only if we started it."""
        if not self.we_started_it or not self.process:
            return

        try:
            if hasattr(os, "killpg"):
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            else:
                self.process.terminate()
            self.process.wait(timeout=5)
            self.logger.info("Stopped Ollama")
        except Exception as e:
            self.logger.warning(f"Error stopping Ollama: {e}")
        finally:
            self.process = None
            self.we_started_it = False
            self.is_running = False


# ─── Custom Widgets ──────────────────────────────────────────────────────────

class RoundedButton(tk.Canvas):
    """A button with seamless rounded corners using polygon drawing."""

    def __init__(self, parent, text="", command=None, width=120, height=36,
                 bg_color="#007aff", fg_color="white", hover_color=None,
                 font_size=13, bold=False, radius=8, **kwargs):
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, **kwargs)

        self.command = command
        self.bg_color = bg_color
        self.fg_color = fg_color
        self.hover_color = hover_color or bg_color
        self.text = text
        self.radius = radius
        self._width = width
        self._height = height
        self._enabled = True
        self._font_size = font_size
        self._bold = bold

        # Inherit parent background
        try:
            self.configure(bg=parent["bg"])
        except Exception:
            pass

        self._draw(self.bg_color)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_click)
        self.config(cursor="hand2")

    def _rounded_rect_points(self, w, h, r):
        """Compute polygon points for a smooth rounded rectangle."""
        points = []
        segs = 12  # segments per corner

        # Standard parametric circle: x = cx + r*cos(θ), y = cy + r*sin(θ)
        # Corners listed clockwise starting from top-left
        corners = [
            (r,     r,     math.pi,         3 * math.pi / 2),  # Top-left
            (w - r, r,     3 * math.pi / 2, 2 * math.pi),      # Top-right
            (w - r, h - r, 0,               math.pi / 2),       # Bottom-right
            (r,     h - r, math.pi / 2,     math.pi),           # Bottom-left
        ]

        for cx, cy, start, end in corners:
            for i in range(segs + 1):
                angle = start + (i / segs) * (end - start)
                points.append(cx + r * math.cos(angle))
                points.append(cy + r * math.sin(angle))

        return points

    def _draw(self, fill):
        self.delete("all")
        w, h = self._width, self._height
        r = min(self.radius, w // 2, h // 2)

        points = self._rounded_rect_points(w, h, r)
        self.create_polygon(points, fill=fill, outline="", smooth=False)

        weight = "bold" if self._bold else "normal"
        fg = self.fg_color if self._enabled else "#98989d"
        self.create_text(
            w / 2, h / 2, text=self.text,
            fill=fg, font=(FONT_FALLBACK[0], self._font_size, weight)
        )

    def _on_enter(self, e):
        if self._enabled:
            self._draw(self.hover_color)

    def _on_leave(self, e):
        color = self.bg_color if self._enabled else "#d2d2d7"
        self._draw(color)

    def _on_click(self, e):
        if self._enabled and self.command:
            self.command()

    def set_enabled(self, enabled):
        self._enabled = enabled
        if enabled:
            self._draw(self.bg_color)
            self.config(cursor="hand2")
        else:
            self._draw("#d2d2d7")
            self.config(cursor="arrow")

    def set_text(self, text):
        self.text = text
        color = self.bg_color if self._enabled else "#d2d2d7"
        self._draw(color)

    def set_colors(self, bg_color, hover_color=None):
        self.bg_color = bg_color
        self.hover_color = hover_color or bg_color
        color = self.bg_color if self._enabled else "#d2d2d7"
        self._draw(color)

    def update_parent_bg(self, bg):
        try:
            self.configure(bg=bg)
        except Exception:
            pass
        color = self.bg_color if self._enabled else "#d2d2d7"
        self._draw(color)


class IconButton(tk.Canvas):
    """A compact button with a Canvas-drawn icon (copy, clear, etc.)."""

    def __init__(self, parent, icon_type="copy", command=None, size=34,
                 bg_color="#e5e5ea", hover_color="#d2d2d7", fg_color="#1d1d1f",
                 tooltip_text="", **kwargs):
        super().__init__(parent, width=size, height=size,
                         highlightthickness=0, **kwargs)
        self.command = command
        self.icon_type = icon_type
        self.size = size
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.fg_color = fg_color
        self._enabled = True
        self.tooltip_text = tooltip_text
        self._tooltip_window = None

        try:
            self.configure(bg=parent["bg"])
        except Exception:
            pass

        self._draw(self.bg_color)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_click)
        self.config(cursor="hand2")

    def _draw(self, fill):
        self.delete("all")
        s = self.size
        r = 6

        # Rounded background — same correct parametric approach as RoundedButton
        points = []
        segs = 8
        corners = [
            (r,     r,     math.pi,         3 * math.pi / 2),  # Top-left
            (s - r, r,     3 * math.pi / 2, 2 * math.pi),      # Top-right
            (s - r, s - r, 0,               math.pi / 2),       # Bottom-right
            (r,     s - r, math.pi / 2,     math.pi),           # Bottom-left
        ]
        for cx, cy, start, end in corners:
            for i in range(segs + 1):
                a = start + (i / segs) * (end - start)
                points += [cx + r * math.cos(a), cy + r * math.sin(a)]

        self.create_polygon(points, fill=fill, outline="", smooth=False)

        fg = self.fg_color if self._enabled else "#98989d"

        if self.icon_type == "copy":
            self._draw_copy_icon(fg)
        elif self.icon_type == "clear":
            self._draw_clear_icon(fg)

    def _draw_copy_icon(self, fg):
        """Draw a clipboard/copy icon."""
        s = self.size
        cx, cy = s / 2, s / 2
        # Back rectangle
        self.create_rectangle(cx - 5, cy - 3, cx + 3, cy + 7,
                              outline=fg, width=1.5, fill="")
        # Front rectangle (overlapping)
        self.create_rectangle(cx - 2, cy - 7, cx + 6, cy + 3,
                              outline=fg, width=1.5, fill=self.bg_color)

    def _draw_clear_icon(self, fg):
        """Draw an X icon."""
        s = self.size
        cx, cy = s / 2, s / 2
        d = 5
        self.create_line(cx - d, cy - d, cx + d, cy + d, fill=fg, width=2)
        self.create_line(cx + d, cy - d, cx - d, cy + d, fill=fg, width=2)

    def _on_enter(self, e):
        if self._enabled:
            self._draw(self.hover_color)
            if self.tooltip_text:
                self._show_tooltip()

    def _on_leave(self, e):
        self._draw(self.bg_color if self._enabled else "#d2d2d7")
        self._hide_tooltip()

    def _on_click(self, e):
        if self._enabled and self.command:
            self.command()

    def _show_tooltip(self):
        if self._tooltip_window:
            return
        x = self.winfo_rootx() + self.size // 2
        y = self.winfo_rooty() + self.size + 4
        tw = tk.Toplevel(self)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.tooltip_text, bg="#333336", fg="#ffffff",
                         font=(FONT_FALLBACK[0], 10), padx=6, pady=2)
        label.pack()
        self._tooltip_window = tw

    def _hide_tooltip(self):
        if self._tooltip_window:
            self._tooltip_window.destroy()
            self._tooltip_window = None

    def set_colors(self, bg_color, hover_color, fg_color):
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.fg_color = fg_color
        self._draw(self.bg_color)

    def update_parent_bg(self, bg):
        try:
            self.configure(bg=bg)
        except Exception:
            pass
        self._draw(self.bg_color)


class MediaButton(tk.Canvas):
    """A circular media control button (Record, Pause, Stop)."""

    def __init__(self, parent, icon_type="record", command=None, size=44,
                 bg_color="#007aff", hover_color="#0063d1", fg_color="white",
                 **kwargs):
        super().__init__(parent, width=size, height=size,
                         highlightthickness=0, **kwargs)
        self.command = command
        self.icon_type = icon_type
        self.size = size
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.fg_color = fg_color
        self._enabled = True

        try:
            self.configure(bg=parent["bg"])
        except Exception:
            pass

        self._draw(self.bg_color)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_click)
        self.config(cursor="hand2")

    def _draw(self, fill):
        self.delete("all")
        s = self.size
        pad = 2

        # Circular background
        self.create_oval(pad, pad, s - pad, s - pad, fill=fill, outline="")

        fg = self.fg_color if self._enabled else "#98989d"
        cx, cy = s / 2, s / 2

        if self.icon_type == "record":
            # Filled circle
            self.create_oval(cx - 8, cy - 8, cx + 8, cy + 8, fill=fg, outline="")
        elif self.icon_type == "pause":
            # Two vertical bars
            self.create_rectangle(cx - 6, cy - 7, cx - 2, cy + 7, fill=fg, outline="")
            self.create_rectangle(cx + 2, cy - 7, cx + 6, cy + 7, fill=fg, outline="")
        elif self.icon_type == "stop":
            # Filled square
            self.create_rectangle(cx - 7, cy - 7, cx + 7, cy + 7, fill=fg, outline="")

    def _on_enter(self, e):
        if self._enabled:
            self._draw(self.hover_color)

    def _on_leave(self, e):
        color = self.bg_color if self._enabled else "#d2d2d7"
        self._draw(color)

    def _on_click(self, e):
        if self._enabled and self.command:
            self.command()

    def set_enabled(self, enabled):
        self._enabled = enabled
        if enabled:
            self._draw(self.bg_color)
            self.config(cursor="hand2")
        else:
            self._draw("#d2d2d7")
            self.config(cursor="arrow")

    def set_colors(self, bg_color, hover_color=None):
        self.bg_color = bg_color
        self.hover_color = hover_color or bg_color
        self._draw(self.bg_color if self._enabled else "#d2d2d7")

    def update_parent_bg(self, bg):
        try:
            self.configure(bg=bg)
        except Exception:
            pass
        self._draw(self.bg_color if self._enabled else "#d2d2d7")


# ─── Main Application ────────────────────────────────────────────────────────

class VoiceScribe:
    def __init__(self, root):
        self.root = root
        self.root.title("VoiceScribe")
        self.root.geometry("740x720")
        self.root.minsize(560, 520)

        # Theme
        self.theme = ThemeManager()
        self.root.configure(bg=self.theme.c("bg"))

        # macOS-specific
        if IS_MAC:
            try:
                self.root.createcommand("tk::mac::Quit", self._on_close)
            except Exception:
                pass

        # State
        self.is_recording = False
        self.is_paused = False
        self.audio_frames = []
        self.model = None
        self.model_size = "base"
        self.stream = None
        self.history = []
        self.history_chars = 0
        self.recording_start_time = None
        self._closing = False
        self._temp_files = set()
        self._recording_timer_id = None
        self._settings_visible = False
        self._info_tooltip_win = None

        # Microphone selection
        self._mic_devices = []  # [(device_index, device_name), ...]
        self._selected_mic_index = None  # None = system default
        self._selected_language = None   # None = auto-detect

        # Ollama — use bundled binary if available (set by .app launcher)
        bundled_ollama = os.environ.get("VOICESCRIBE_BUNDLED_OLLAMA")
        self.ollama = OllamaManager(bundled_path=bundled_ollama)

        # Logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[logging.StreamHandler(sys.stdout)],
        )
        self.logger = logging.getLogger("VoiceScribe")

        # Track all themed widgets for runtime switching
        self._themed_frames = []
        self._themed_labels = []

        self._configure_styles()
        self._setup_gui()
        self._show_privacy_notice_if_needed()
        self._load_model_async()
        self._check_ollama_async()

        # Keyboard shortcuts
        self.root.bind("<space>", self._on_space)

        # Cleanup handlers
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        atexit.register(self._cleanup)
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, lambda s, f: self.root.after(0, self._on_close))
            except (OSError, ValueError):
                pass

        # Periodic Ollama health check
        self._schedule_ollama_health_check()

        # Populate mic list and start periodic refresh
        self._refresh_mic_list()
        self._update_mic_indicator()
        self._schedule_mic_refresh()

        self.logger.info(f"VoiceScribe {APP_VERSION} started")

    # ── Styles ────────────────────────────────────────────────────────────

    def _configure_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("aqua" if IS_MAC else "clam")
        except Exception:
            style.theme_use("clam")
        style.configure("TCombobox", padding=4)

    # ── GUI Setup (grid-based) ────────────────────────────────────────────

    def _setup_gui(self):
        c = self.theme.c
        pad_x = 20

        # Configure grid
        self.root.grid_rowconfigure(2, weight=1)  # Text area expands
        self.root.grid_columnconfigure(0, weight=1)

        # ── Row 0: Header ────────────────────────────────────────────────
        header = tk.Frame(self.root, bg=c("bg"))
        header.grid(row=0, column=0, sticky="ew", padx=pad_x, pady=(16, 0))
        self._themed_frames.append(header)
        self.header = header

        title = tk.Label(header, text="VoiceScribe", fg=c("text"),
                         bg=c("bg"), font=(FONT_FALLBACK[0], 20, "bold"))
        title.pack(side=tk.LEFT)
        self._themed_labels.append(("text", "bg", title))
        self.title_label = title

        # Status indicator
        status_frame = tk.Frame(header, bg=c("bg"))
        status_frame.pack(side=tk.LEFT, padx=(12, 0))
        self._themed_frames.append(status_frame)

        self.status_dot = tk.Label(status_frame, text="\u25cf", fg=c("warning"),
                                   bg=c("bg"), font=(FONT_FALLBACK[0], 8))
        self.status_dot.pack(side=tk.LEFT)
        self._themed_labels.append((None, "bg", self.status_dot))

        self.status_label = tk.Label(status_frame, text="  Loading...",
                                     fg=c("text_secondary"), bg=c("bg"),
                                     font=(FONT_FALLBACK[0], 12))
        self.status_label.pack(side=tk.LEFT)
        self._themed_labels.append(("text_secondary", "bg", self.status_label))

        # Theme toggle (right side of header)
        theme_frame = tk.Frame(header, bg=c("bg"))
        theme_frame.pack(side=tk.RIGHT)
        self._themed_frames.append(theme_frame)

        self.theme_mode_idx = {"light": 0, "dark": 1, "system": 2}[self.theme.mode]
        theme_icons = ["\u2600\ufe0f", "\u263e", "Auto"]
        self.theme_btn = RoundedButton(
            theme_frame, text=theme_icons[self.theme_mode_idx],
            command=self._cycle_theme,
            width=56, height=30, bg_color=c("border_light"),
            hover_color=c("border"), fg_color=c("text"),
            font_size=12, radius=6
        )
        self.theme_btn.pack(side=tk.RIGHT)

        # ── Row 1: Separator ─────────────────────────────────────────────
        sep = tk.Frame(self.root, bg=c("border_light"), height=1)
        sep.grid(row=1, column=0, sticky="ew", padx=pad_x, pady=(12, 0))
        self.sep = sep

        # ── Row 2: Text Area (expands) ───────────────────────────────────
        text_container = tk.Frame(self.root, bg=c("bg"))
        text_container.grid(row=2, column=0, sticky="nsew", padx=pad_x, pady=(12, 0))
        text_container.grid_rowconfigure(1, weight=1)
        text_container.grid_columnconfigure(0, weight=1)
        self._themed_frames.append(text_container)
        self.text_container = text_container

        # Text header row
        text_header = tk.Frame(text_container, bg=c("bg"))
        text_header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self._themed_frames.append(text_header)

        text_title = tk.Label(text_header, text="Transcription", fg=c("text"),
                              bg=c("bg"), font=(FONT_FALLBACK[0], 13, "bold"))
        text_title.pack(side=tk.LEFT)
        self._themed_labels.append(("text", "bg", text_title))

        self.timer_label = tk.Label(text_header, text="", fg=c("text_secondary"),
                                    bg=c("bg"), font=(FONT_FALLBACK[0], 13))
        self.timer_label.pack(side=tk.RIGHT)
        self._themed_labels.append(("text_secondary", "bg", self.timer_label))

        # Text area with border
        text_border = tk.Frame(text_container, bg=c("border"), padx=1, pady=1)
        text_border.grid(row=1, column=0, sticky="nsew")
        self.text_border = text_border

        self.text_area = scrolledtext.ScrolledText(
            text_border, wrap=tk.WORD,
            font=(FONT_FALLBACK[0], 14),
            bg=c("surface"), fg=c("text"),
            insertbackground=c("text"),
            selectbackground=c("selection"),
            selectforeground=c("text"),
            relief=tk.FLAT, borderwidth=10,
            highlightthickness=0,
        )
        self.text_area.pack(fill=tk.BOTH, expand=True)
        self.text_area.bind("<Key>", self._on_text_key)
        self._show_placeholder()

        # ── Row 3: Media Controls ────────────────────────────────────────
        btn_frame = tk.Frame(self.root, bg=c("bg"))
        btn_frame.grid(row=3, column=0, sticky="ew", padx=pad_x, pady=(12, 0))
        self._themed_frames.append(btn_frame)
        self.btn_frame = btn_frame

        # Record button
        self.record_btn = MediaButton(
            btn_frame, icon_type="record", command=self._on_record_click,
            size=44, bg_color=c("record"), hover_color=c("record_hover")
        )
        self.record_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.record_btn.set_enabled(False)

        # Pause button
        self.pause_btn = MediaButton(
            btn_frame, icon_type="pause", command=self._on_pause_click,
            size=44, bg_color=c("pause"), hover_color=c("pause_hover")
        )
        self.pause_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.pause_btn.set_enabled(False)

        # Stop button
        self.stop_btn = MediaButton(
            btn_frame, icon_type="stop", command=self._on_stop_click,
            size=44, bg_color=c("stop"), hover_color=c("stop_hover")
        )
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 12))
        self.stop_btn.set_enabled(False)

        # Copy icon button
        self.copy_btn = IconButton(
            btn_frame, icon_type="copy", command=self._copy_to_clipboard,
            size=34, bg_color=c("border_light"), hover_color=c("border"),
            fg_color=c("text"), tooltip_text="Copy to clipboard"
        )
        self.copy_btn.pack(side=tk.LEFT, padx=(0, 4))

        # Clear icon button
        self.clear_btn = IconButton(
            btn_frame, icon_type="clear", command=self._clear_text,
            size=34, bg_color=c("border_light"), hover_color=c("border"),
            fg_color=c("text"), tooltip_text="Clear text"
        )
        self.clear_btn.pack(side=tk.LEFT, padx=(0, 6))

        # Append toggle (right side)
        self.append_var = tk.BooleanVar(value=False)
        self.append_check = tk.Checkbutton(
            btn_frame, text="Append", variable=self.append_var,
            fg=c("text_secondary"), bg=c("bg"),
            activebackground=c("bg"), activeforeground=c("text"),
            selectcolor=c("surface"),
            font=(FONT_FALLBACK[0], 11)
        )
        self.append_check.pack(side=tk.RIGHT)

        # Active mic indicator (right side, before Append)
        self.mic_indicator = tk.Label(
            btn_frame, text="\U0001f3a4 Default",
            fg=c("text_secondary"), bg=c("bg"),
            font=(FONT_FALLBACK[0], 10)
        )
        self.mic_indicator.pack(side=tk.RIGHT, padx=(0, 10))
        self._themed_labels.append(("text_secondary", "bg", self.mic_indicator))

        # ── Row 4: AI Polish Bar ─────────────────────────────────────────
        polish_frame = tk.Frame(self.root, bg=c("bg"))
        polish_frame.grid(row=4, column=0, sticky="ew", padx=pad_x, pady=(10, 0))
        self._themed_frames.append(polish_frame)
        self.polish_frame = polish_frame

        self.polish_btn = RoundedButton(
            polish_frame, text="Polish Text", command=self._refine_text,
            width=120, height=34, bg_color=c("polish"),
            hover_color=c("polish_hover"), font_size=12, bold=True
        )
        self.polish_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.polish_btn.set_enabled(False)

        self.ollama_status_label = tk.Label(
            polish_frame, text="Checking AI Engine...", fg=c("text_secondary"),
            bg=c("bg"), font=(FONT_FALLBACK[0], 11)
        )
        self.ollama_status_label.pack(side=tk.LEFT)
        self._themed_labels.append((None, "bg", self.ollama_status_label))

        # Settings toggle (right side)
        self.settings_btn = RoundedButton(
            polish_frame, text="\u2699 Settings", command=self._toggle_settings,
            width=96, height=30, bg_color=c("border_light"),
            hover_color=c("border"), fg_color=c("text"),
            font_size=11, radius=6
        )
        self.settings_btn.pack(side=tk.RIGHT)

        # ── Row 5: Collapsible Settings Panel ────────────────────────────
        self.settings_panel = tk.Frame(self.root, bg=c("settings_bg"))
        # NOT gridded initially — hidden by default
        self._build_settings_panel()

        # ── Row 6: History ───────────────────────────────────────────────
        history_container = tk.Frame(self.root, bg=c("bg"))
        history_container.grid(row=6, column=0, sticky="ew", padx=pad_x, pady=(12, 0))
        self._themed_frames.append(history_container)
        self.history_container = history_container

        hist_title = tk.Label(history_container, text="History", fg=c("text"),
                              bg=c("bg"), font=(FONT_FALLBACK[0], 13, "bold"))
        hist_title.pack(anchor="w", pady=(0, 4))
        self._themed_labels.append(("text", "bg", hist_title))

        history_border = tk.Frame(history_container, bg=c("border"), padx=1, pady=1)
        history_border.pack(fill=tk.X)
        self.history_border = history_border

        self.history_listbox = tk.Listbox(
            history_border, height=3,
            font=(FONT_FALLBACK[0], 12),
            bg=c("surface"), fg=c("text"),
            selectbackground=c("accent"),
            selectforeground="white",
            relief=tk.FLAT, borderwidth=6,
            activestyle="none",
            highlightthickness=0,
        )
        self.history_listbox.pack(fill=tk.X)
        self.history_listbox.bind("<<ListboxSelect>>", self._on_history_select)

        # ── Row 7: Footer ────────────────────────────────────────────────
        footer = tk.Label(
            self.root,
            text=f"Space = Record/Pause  \u2022  v{APP_VERSION}",
            fg=c("text_secondary"), bg=c("bg"),
            font=(FONT_FALLBACK[0], 10)
        )
        footer.grid(row=7, column=0, sticky="ew", pady=(8, 12))
        self._themed_labels.append(("text_secondary", "bg", footer))
        self.footer = footer

    # ── Settings Panel ───────────────────────────────────────────────────

    def _build_settings_panel(self):
        c = self.theme.c
        panel = self.settings_panel
        panel.configure(bg=c("settings_bg"))
        inner_pad = 12

        # Container with padding
        inner = tk.Frame(panel, bg=c("settings_bg"), padx=inner_pad, pady=8)
        inner.pack(fill=tk.X)
        self._themed_frames.append(inner)
        self.settings_inner = inner

        # Row 0: Microphone
        row0 = tk.Frame(inner, bg=c("settings_bg"))
        row0.pack(fill=tk.X, pady=(0, 8))
        self._themed_frames.append(row0)

        mic_label = tk.Label(row0, text="Microphone",
                             fg=c("text"), bg=c("settings_bg"),
                             font=(FONT_FALLBACK[0], 12))
        mic_label.pack(side=tk.LEFT)
        self._themed_labels.append(("text", "settings_bg", mic_label))

        # Refresh button
        self.mic_refresh_btn = RoundedButton(
            row0, text="\u21bb", command=self._refresh_mic_list,
            width=30, height=24, bg_color=c("border_light"),
            hover_color=c("border"), fg_color=c("text"),
            font_size=12, radius=4
        )
        self.mic_refresh_btn.pack(side=tk.RIGHT, padx=(4, 0))

        self.mic_var = tk.StringVar(value="System Default")
        self.mic_combo = ttk.Combobox(
            row0, textvariable=self.mic_var,
            values=["System Default"], state="readonly", width=28
        )
        self.mic_combo.pack(side=tk.RIGHT)
        self.mic_combo.bind("<<ComboboxSelected>>", self._on_mic_change)

        # Row 1: Language
        row_lang = tk.Frame(inner, bg=c("settings_bg"))
        row_lang.pack(fill=tk.X, pady=(0, 8))
        self._themed_frames.append(row_lang)

        lang_label = tk.Label(row_lang, text="Language",
                              fg=c("text"), bg=c("settings_bg"),
                              font=(FONT_FALLBACK[0], 12))
        lang_label.pack(side=tk.LEFT)
        self._themed_labels.append(("text", "settings_bg", lang_label))

        self.lang_var = tk.StringVar(value="Auto-detect")
        self.lang_combo = ttk.Combobox(
            row_lang, textvariable=self.lang_var,
            values=list(LANGUAGES.keys()), state="readonly", width=16
        )
        self.lang_combo.pack(side=tk.RIGHT)
        self.lang_combo.bind("<<ComboboxSelected>>", self._on_language_change)

        lang_hint = tk.Label(row_lang, text="Faster when set explicitly",
                             fg=c("text_secondary"), bg=c("settings_bg"),
                             font=(FONT_FALLBACK[0], 10))
        lang_hint.pack(side=tk.RIGHT, padx=(0, 8))
        self._themed_labels.append(("text_secondary", "settings_bg", lang_hint))

        # Row 2: Transcription Accuracy
        row1 = tk.Frame(inner, bg=c("settings_bg"))
        row1.pack(fill=tk.X, pady=(0, 8))
        self._themed_frames.append(row1)

        acc_label = tk.Label(row1, text="Transcription Accuracy",
                             fg=c("text"), bg=c("settings_bg"),
                             font=(FONT_FALLBACK[0], 12))
        acc_label.pack(side=tk.LEFT)
        self._themed_labels.append(("text", "settings_bg", acc_label))

        # Info tooltip
        info_label = tk.Label(row1, text="\u24d8", fg=c("text_secondary"),
                              bg=c("settings_bg"),
                              font=(FONT_FALLBACK[0], 11), cursor="hand2")
        info_label.pack(side=tk.LEFT, padx=(4, 0))
        info_label.bind("<Enter>", lambda e: self._show_info_tooltip(
            info_label, "Controls how accurately speech is converted to text.\nHigher accuracy uses more CPU and takes longer."))
        info_label.bind("<Leave>", lambda e: self._hide_info_tooltip())
        self._themed_labels.append(("text_secondary", "settings_bg", info_label))

        self.whisper_var = tk.StringVar(value="Balanced")
        self.whisper_combo = ttk.Combobox(
            row1, textvariable=self.whisper_var,
            values=WHISPER_DISPLAY_NAMES, state="readonly", width=12
        )
        self.whisper_combo.pack(side=tk.RIGHT)
        self.whisper_combo.bind("<<ComboboxSelected>>", self._on_whisper_change)

        whisper_desc = tk.Label(row1, text="Good speed and accuracy",
                                fg=c("text_secondary"), bg=c("settings_bg"),
                                font=(FONT_FALLBACK[0], 10))
        whisper_desc.pack(side=tk.RIGHT, padx=(0, 8))
        self.whisper_desc_label = whisper_desc
        self._themed_labels.append(("text_secondary", "settings_bg", whisper_desc))

        # Row 2: AI Polish Model
        row2 = tk.Frame(inner, bg=c("settings_bg"))
        row2.pack(fill=tk.X, pady=(0, 8))
        self._themed_frames.append(row2)

        llm_label = tk.Label(row2, text="AI Polish Model",
                             fg=c("text"), bg=c("settings_bg"),
                             font=(FONT_FALLBACK[0], 12))
        llm_label.pack(side=tk.LEFT)
        self._themed_labels.append(("text", "settings_bg", llm_label))

        self.ollama_model_var = tk.StringVar(value=OLLAMA_DEFAULT_MODEL)
        self.ollama_model_combo = ttk.Combobox(
            row2, textvariable=self.ollama_model_var,
            values=[], state="readonly", width=18
        )
        self.ollama_model_combo.pack(side=tk.RIGHT)

        llm_desc = tk.Label(row2, text="Cleans up raw speech into polished text",
                            fg=c("text_secondary"), bg=c("settings_bg"),
                            font=(FONT_FALLBACK[0], 10))
        llm_desc.pack(side=tk.RIGHT, padx=(0, 8))
        self._themed_labels.append(("text_secondary", "settings_bg", llm_desc))

        # Row 3: AI Engine control
        row3 = tk.Frame(inner, bg=c("settings_bg"))
        row3.pack(fill=tk.X)
        self._themed_frames.append(row3)

        engine_label = tk.Label(row3, text="AI Engine (Ollama)",
                                fg=c("text"), bg=c("settings_bg"),
                                font=(FONT_FALLBACK[0], 12))
        engine_label.pack(side=tk.LEFT)
        self._themed_labels.append(("text", "settings_bg", engine_label))

        self.ollama_toggle_btn = RoundedButton(
            row3, text="Start", command=self._toggle_ollama,
            width=72, height=28, bg_color=c("success"),
            hover_color="#2ab84e", fg_color="white",
            font_size=11, radius=6
        )
        self.ollama_toggle_btn.pack(side=tk.RIGHT)

        self.ollama_engine_status = tk.Label(
            row3, text="Checking...", fg=c("text_secondary"),
            bg=c("settings_bg"), font=(FONT_FALLBACK[0], 11)
        )
        self.ollama_engine_status.pack(side=tk.RIGHT, padx=(0, 8))
        self._themed_labels.append((None, "settings_bg", self.ollama_engine_status))

        # Row 4: Bundle status info
        row4 = tk.Frame(inner, bg=c("settings_bg"))
        row4.pack(fill=tk.X, pady=(8, 0))
        self._themed_frames.append(row4)

        is_bundled = bool(os.environ.get("VOICESCRIBE_BUNDLED_OLLAMA"))
        bundle_text = "All AI models bundled — fully offline" if is_bundled else "Running in development mode"
        self.bundle_info_label = tk.Label(
            row4, text=bundle_text,
            fg=c("success") if is_bundled else c("text_secondary"),
            bg=c("settings_bg"), font=(FONT_FALLBACK[0], 10)
        )
        self.bundle_info_label.pack(side=tk.LEFT)

    def _toggle_settings(self):
        if self._settings_visible:
            self.settings_panel.grid_forget()
            self._settings_visible = False
        else:
            self.settings_panel.grid(row=5, column=0, sticky="ew", padx=20, pady=(6, 0))
            self._settings_visible = True

    def _show_info_tooltip(self, widget, text):
        if hasattr(self, '_info_tooltip_win') and self._info_tooltip_win:
            return
        x = widget.winfo_rootx() + widget.winfo_width() + 4
        y = widget.winfo_rooty()
        tw = tk.Toplevel(self.root)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=text, bg=self.theme.c("tooltip_bg"),
                         fg=self.theme.c("tooltip_fg"),
                         font=(FONT_FALLBACK[0], 10), padx=8, pady=4,
                         justify=tk.LEFT)
        label.pack()
        self._info_tooltip_win = tw

    def _hide_info_tooltip(self):
        if hasattr(self, '_info_tooltip_win') and self._info_tooltip_win:
            self._info_tooltip_win.destroy()
            self._info_tooltip_win = None

    # ── Theme Switching ──────────────────────────────────────────────────

    def _cycle_theme(self):
        modes = ["light", "dark", "system"]
        icons = ["\u2600\ufe0f", "\u263e", "Auto"]
        self.theme_mode_idx = (self.theme_mode_idx + 1) % 3
        new_mode = modes[self.theme_mode_idx]
        self.theme.set_mode(new_mode)
        self.theme_btn.set_text(icons[self.theme_mode_idx])
        self._apply_theme()

    def _apply_theme(self):
        c = self.theme.c

        # Root
        self.root.configure(bg=c("bg"))

        # All tracked frames
        for frame in self._themed_frames:
            try:
                # Settings frames use settings_bg, others use bg
                if frame in (self.settings_inner,) or frame.master == self.settings_inner:
                    frame.configure(bg=c("settings_bg"))
                else:
                    frame.configure(bg=c("bg"))
            except Exception:
                pass

        # All tracked labels
        for fg_key, bg_key, label in self._themed_labels:
            try:
                label.configure(bg=c(bg_key))
                if fg_key:
                    label.configure(fg=c(fg_key))
            except Exception:
                pass

        # Settings panel background
        self.settings_panel.configure(bg=c("settings_bg"))

        # Separator
        self.sep.configure(bg=c("border_light"))

        # Text area
        self.text_area.configure(
            bg=c("surface"), fg=c("text"),
            insertbackground=c("text"),
            selectbackground=c("selection"),
        )
        self.text_border.configure(bg=c("border"))

        # History
        self.history_listbox.configure(
            bg=c("surface"), fg=c("text"),
            selectbackground=c("accent"),
        )
        self.history_border.configure(bg=c("border"))

        # Buttons
        self.record_btn.set_colors(c("record"), c("record_hover"))
        self.record_btn.update_parent_bg(c("bg"))
        self.pause_btn.set_colors(c("pause"), c("pause_hover"))
        self.pause_btn.update_parent_bg(c("bg"))
        self.stop_btn.set_colors(c("stop"), c("stop_hover"))
        self.stop_btn.update_parent_bg(c("bg"))

        self.copy_btn.set_colors(c("border_light"), c("border"), c("text"))
        self.copy_btn.update_parent_bg(c("bg"))
        self.clear_btn.set_colors(c("border_light"), c("border"), c("text"))
        self.clear_btn.update_parent_bg(c("bg"))

        self.polish_btn.set_colors(c("polish"), c("polish_hover"))
        self.polish_btn.update_parent_bg(c("bg"))

        self.theme_btn.set_colors(c("border_light"), c("border"))
        self.theme_btn.fg_color = c("text")
        self.theme_btn.update_parent_bg(c("bg"))

        self.settings_btn.set_colors(c("border_light"), c("border"))
        self.settings_btn.fg_color = c("text")
        self.settings_btn.update_parent_bg(c("bg"))

        # Mic refresh button
        self.mic_refresh_btn.set_colors(c("border_light"), c("border"))
        self.mic_refresh_btn.fg_color = c("text")
        self.mic_refresh_btn.update_parent_bg(c("settings_bg"))

        # Append checkbox
        self.append_check.configure(
            fg=c("text_secondary"), bg=c("bg"),
            activebackground=c("bg"), activeforeground=c("text"),
            selectcolor=c("surface")
        )

    # ── Placeholder ──────────────────────────────────────────────────────

    def _show_placeholder(self):
        if not self.text_area.get("1.0", tk.END).strip():
            self.text_area.insert("1.0", "Click Record or press Space to start...")
            self.text_area.config(fg=self.theme.c("text_secondary"))
            self._placeholder_visible = True
        else:
            self._placeholder_visible = False

    def _hide_placeholder(self):
        if getattr(self, "_placeholder_visible", False):
            self.text_area.delete("1.0", tk.END)
            self.text_area.config(fg=self.theme.c("text"))
            self._placeholder_visible = False

    # ── Whisper Model ────────────────────────────────────────────────────

    def _load_model_async(self):
        self.record_btn.set_enabled(False)
        self._set_status("loading", f"Loading model...")

        def load():
            try:
                model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
                self.model = model
                self.root.after(0, lambda: self._set_status("ready", "Ready"))
                self.root.after(0, lambda: self.record_btn.set_enabled(True))
            except Exception as e:
                self.root.after(0, lambda: self._set_status("error", f"Model error: {e}"))

        threading.Thread(target=load, daemon=True).start()

    def _on_whisper_change(self, event=None):
        display_name = self.whisper_var.get()
        idx = WHISPER_DISPLAY_NAMES.index(display_name)
        new_size = WHISPER_SIZES[idx]
        desc = WHISPER_LABELS[new_size][1]
        self.whisper_desc_label.config(text=desc)

        if new_size != self.model_size:
            self.model_size = new_size
            self.model = None
            self._load_model_async()

    # ── Microphone Selection ────────────────────────────────────────────

    def _refresh_mic_list(self):
        """Query available input devices and update the mic combo box."""
        try:
            devices = sd.query_devices()
            self._mic_devices = [
                (i, d["name"])
                for i, d in enumerate(devices)
                if d["max_input_channels"] > 0
            ]
        except Exception as e:
            self.logger.warning(f"Could not enumerate audio devices: {e}")
            self._mic_devices = []

        # Build display names: "System Default" + all input devices
        display_names = ["System Default"]
        display_names += [name for _, name in self._mic_devices]

        if hasattr(self, "mic_combo"):
            self.mic_combo.config(values=display_names)
            # Keep current selection if still valid, else reset
            current = self.mic_var.get()
            if current not in display_names:
                self.mic_var.set("System Default")
                self._selected_mic_index = None
                self._update_mic_indicator()

    def _on_mic_change(self, event=None):
        """Handle mic dropdown selection change."""
        selected = self.mic_var.get()
        if selected == "System Default":
            self._selected_mic_index = None
        else:
            # Find matching device index
            for dev_idx, dev_name in self._mic_devices:
                if dev_name == selected:
                    self._selected_mic_index = dev_idx
                    break

        self._update_mic_indicator()
        self.logger.info(f"Mic changed: {selected} (device={self._selected_mic_index})")

        # Warn if currently recording
        if self.is_recording:
            self._set_status("warning", "Mic change takes effect on next recording")

    def _on_language_change(self, event=None):
        """Handle language dropdown selection change."""
        selected = self.lang_var.get()
        self._selected_language = LANGUAGES.get(selected)
        self.logger.info(f"Language changed: {selected} (code={self._selected_language})")

    def _update_mic_indicator(self):
        """Update the mic indicator label in the main UI."""
        if not hasattr(self, "mic_indicator"):
            return

        if self._selected_mic_index is None:
            # Resolve the actual default device name
            try:
                default_info = sd.query_devices(kind="input")
                name = default_info["name"]
            except Exception:
                name = "Default"
        else:
            name = self.mic_var.get()

        # Truncate long names
        if len(name) > 40:
            name = name[:37] + "..."

        self.mic_indicator.config(text=f"\U0001f3a4 {name}")

    def _schedule_mic_refresh(self):
        """Periodically refresh the mic list to catch hot-plugged devices."""
        self._refresh_mic_list()
        self.root.after(30000, self._schedule_mic_refresh)

    # ── Ollama Integration ───────────────────────────────────────────────

    def _check_ollama_async(self):
        def check():
            is_alive = self.ollama.check_health()
            if not is_alive:
                # Ollama server isn't running — try to auto-start if binary exists
                ollama_path = self.ollama.find_ollama()
                if ollama_path:
                    self.root.after(0, lambda: self.ollama_status_label.config(
                        text="AI Engine: Starting...",
                        fg=self.theme.c("warning")
                    ))
                    self.logger.info("Ollama not running — auto-starting...")
                    success = self.ollama.start()
                    if success:
                        self.logger.info(f"Ollama auto-started — {len(self.ollama.models)} model(s) found")
                    else:
                        self.logger.warning("Ollama auto-start failed")
            elif is_alive and not self.ollama.models:
                # Server was already running but models not yet indexed — retry
                self.logger.info("Ollama running but 0 models — retrying...")
                for _ in range(10):
                    time.sleep(1)
                    self.ollama.check_health()
                    if self.ollama.models:
                        self.logger.info(f"Models found after retry: {self.ollama.models}")
                        break
            self.root.after(0, self._update_ollama_ui)

        threading.Thread(target=check, daemon=True).start()

    def _update_ollama_ui(self):
        c = self.theme.c
        is_bundled = bool(os.environ.get("VOICESCRIBE_BUNDLED_OLLAMA"))

        if self.ollama.is_running and self.ollama.models:
            self.polish_btn.set_enabled(True)
            self.ollama_model_combo.config(values=self.ollama.models)
            if OLLAMA_DEFAULT_MODEL in self.ollama.models:
                self.ollama_model_var.set(OLLAMA_DEFAULT_MODEL)
            elif self.ollama.models:
                self.ollama_model_var.set(self.ollama.models[0])

            label = "Bundled AI ready" if is_bundled else "AI Engine: Connected"
            self.ollama_status_label.config(
                text=f"{label} \u2022 {len(self.ollama.models)} models",
                fg=c("success")
            )
            self.ollama_engine_status.config(text="Running", fg=c("success"))
            self.ollama_toggle_btn.set_text("Stop")
            self.ollama_toggle_btn.set_colors(c("record"), c("record_hover"))

        elif self.ollama.is_running and not self.ollama.models:
            self.polish_btn.set_enabled(False)
            if is_bundled:
                self.ollama_status_label.config(
                    text="AI Engine: Model loading...",
                    fg=c("warning")
                )
            else:
                self.ollama_status_label.config(
                    text="AI Engine: No models installed",
                    fg=c("warning")
                )
            self.ollama_engine_status.config(text="No models", fg=c("warning"))
            self.ollama_toggle_btn.set_text("Stop")
            self.ollama_toggle_btn.set_colors(c("record"), c("record_hover"))
        else:
            self.polish_btn.set_enabled(False)
            ollama_path = self.ollama.find_ollama()
            if ollama_path:
                self.ollama_status_label.config(
                    text="AI Engine: Offline — open Settings to start",
                    fg=c("text_secondary")
                )
            else:
                self.ollama_status_label.config(
                    text="AI Engine: Not found — rebuild app bundle",
                    fg=c("warning")
                )
            self.ollama_engine_status.config(text="Offline", fg=c("text_secondary"))
            self.ollama_toggle_btn.set_text("Start")
            self.ollama_toggle_btn.set_colors(c("success"), "#2ab84e")

    def _toggle_ollama(self):
        if self.ollama.is_running:
            if self.ollama.we_started_it:
                self.ollama_toggle_btn.set_enabled(False)
                self.ollama_engine_status.config(text="Stopping...",
                                                 fg=self.theme.c("warning"))

                def do_stop():
                    self.ollama.stop()
                    self.ollama.check_health()
                    self.root.after(0, self._update_ollama_ui)
                    self.root.after(0, lambda: self.ollama_toggle_btn.set_enabled(True))

                threading.Thread(target=do_stop, daemon=True).start()
            else:
                messagebox.showinfo(
                    "AI Engine",
                    "Ollama was started outside VoiceScribe.\n"
                    "Please stop it manually if needed:\n\n"
                    "  killall ollama"
                )
        else:
            self.ollama_toggle_btn.set_enabled(False)
            self.ollama_engine_status.config(text="Starting...",
                                             fg=self.theme.c("warning"))

            def do_start():
                success = self.ollama.start()
                self.root.after(0, self._update_ollama_ui)
                self.root.after(0, lambda: self.ollama_toggle_btn.set_enabled(True))
                if not success:
                    self.root.after(0, lambda: messagebox.showwarning(
                        "AI Engine",
                        "Could not start Ollama.\n\n"
                        "The bundled Ollama binary may be missing.\n"
                        "Try rebuilding the app with create_app.sh."
                    ))

            threading.Thread(target=do_start, daemon=True).start()

    def _schedule_ollama_health_check(self):
        """Check Ollama health every 10 seconds."""
        def check():
            was_running = self.ollama.is_running
            self.ollama.check_health()
            if was_running != self.ollama.is_running:
                self.root.after(0, self._update_ollama_ui)

        def periodic():
            threading.Thread(target=check, daemon=True).start()
            self.root.after(10000, periodic)

        self.root.after(10000, periodic)

    def _refine_text(self):
        raw_text = self.text_area.get("1.0", tk.END).strip()
        if not raw_text or getattr(self, "_placeholder_visible", False):
            self._set_status("ready", "Nothing to polish")
            return

        if not self.ollama.is_running:
            self._set_status("error", "AI Engine not running — open Settings to start")
            return

        model = self.ollama_model_var.get()
        if not model:
            self._set_status("error", "No model selected")
            return

        self.polish_btn.set_enabled(False)
        self.polish_btn.set_text("Polishing...")
        self._set_status("loading", f"Polishing with {model}...")

        def do_refine():
            try:
                refined = self.ollama.generate(
                    model=model, prompt=raw_text,
                    system_prompt=REFINE_SYSTEM_PROMPT,
                )

                def update_ui():
                    if refined:
                        self._hide_placeholder()
                        self.text_area.delete("1.0", tk.END)
                        self.text_area.insert(tk.END, refined)

                        clipboard_msg = ""
                        if CLIPBOARD_AVAILABLE:
                            try:
                                pyperclip.copy(refined)
                                clipboard_msg = " \u2014 copied!"
                            except Exception:
                                pass

                        self._set_status("ready", f"Polished{clipboard_msg}")

                        timestamp = time.strftime("%H:%M")
                        preview = refined[:60] + "..." if len(refined) > 60 else refined
                        self.history.insert(0, refined)
                        self.history_chars += len(refined)
                        self.history_listbox.insert(0, f"{timestamp}  [polished]  {preview}")
                        self._trim_history()
                    else:
                        self._set_status("ready", "No output from AI")

                    self.polish_btn.set_enabled(True)
                    self.polish_btn.set_text("Polish Text")

                self.root.after(0, update_ui)

            except Exception as e:
                def show_error():
                    self._set_status("error", f"Polish failed: {e}")
                    self.polish_btn.set_enabled(True)
                    self.polish_btn.set_text("Polish Text")
                self.root.after(0, show_error)

        threading.Thread(target=do_refine, daemon=True).start()

    # ── Recording (Record / Pause / Stop) ────────────────────────────────

    def _on_record_click(self):
        if self.is_paused:
            self._resume_recording()
        else:
            self._start_recording()

    def _on_pause_click(self):
        if self.is_recording and not self.is_paused:
            self._pause_recording()

    def _on_stop_click(self):
        if self.is_recording or self.is_paused:
            self._stop_recording()

    def _start_recording(self):
        if self.model is None:
            self._set_status("error", "Model not loaded yet")
            return

        self._hide_placeholder()
        self.is_recording = True
        self.is_paused = False
        self.audio_frames = []
        self.recording_start_time = time.time()

        # Button states: record off, pause on, stop on
        self.record_btn.set_enabled(False)
        self.pause_btn.set_enabled(True)
        self.stop_btn.set_enabled(True)

        self._set_status("recording", "Recording...")
        self._update_timer()

        def audio_callback(indata, frames, time_info, status):
            if self.is_recording and not self.is_paused:
                self.audio_frames.append(indata.copy())

        try:
            self.stream = sd.InputStream(
                device=self._selected_mic_index,
                samplerate=SAMPLE_RATE, channels=CHANNELS,
                dtype=DTYPE, callback=audio_callback
            )
            self.stream.start()
        except Exception as e:
            self.is_recording = False
            self._set_status("error", f"Mic error: {e}")
            self.record_btn.set_enabled(True)
            self.pause_btn.set_enabled(False)
            self.stop_btn.set_enabled(False)

    def _pause_recording(self):
        self.is_paused = True

        if self.stream:
            try:
                self.stream.stop()
            except Exception:
                pass

        # Button states: record on (to resume), pause off, stop on
        self.record_btn.set_enabled(True)
        self.pause_btn.set_enabled(False)

        self._set_status("loading", "Paused")

    def _resume_recording(self):
        self.is_paused = False

        def audio_callback(indata, frames, time_info, status):
            if self.is_recording and not self.is_paused:
                self.audio_frames.append(indata.copy())

        try:
            self.stream = sd.InputStream(
                device=self._selected_mic_index,
                samplerate=SAMPLE_RATE, channels=CHANNELS,
                dtype=DTYPE, callback=audio_callback
            )
            self.stream.start()
        except Exception as e:
            self._set_status("error", f"Mic error on resume: {e}")
            return

        # Button states: record off, pause on, stop on
        self.record_btn.set_enabled(False)
        self.pause_btn.set_enabled(True)
        self.stop_btn.set_enabled(True)

        self._set_status("recording", "Recording...")
        self._update_timer()

    def _stop_recording(self):
        self.is_recording = False
        self.is_paused = False

        # Cancel timer
        if self._recording_timer_id:
            try:
                self.root.after_cancel(self._recording_timer_id)
            except Exception:
                pass
            self._recording_timer_id = None

        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception as e:
                self.logger.warning(f"Error closing stream: {e}")
            self.stream = None

        # Button states: all off until transcription done
        self.record_btn.set_enabled(False)
        self.pause_btn.set_enabled(False)
        self.stop_btn.set_enabled(False)
        self.timer_label.config(text="")
        self._set_status("loading", "Transcribing...")

        threading.Thread(target=self._transcribe_audio, daemon=True).start()

    def _update_timer(self):
        if self.is_recording and self.recording_start_time:
            elapsed = time.time() - self.recording_start_time
            mins, secs = divmod(int(elapsed), 60)
            self.timer_label.config(text=f"{mins:02d}:{secs:02d}")

            if elapsed >= MAX_RECORDING_SECONDS:
                self.logger.warning(f"Auto-stopped at {MAX_RECORDING_SECONDS}s limit")
                self._set_status("warning", "Auto-stopped (10 min limit)")
                self._stop_recording()
                return

            self._recording_timer_id = self.root.after(1000, self._update_timer)

    # ── Transcription ────────────────────────────────────────────────────

    def _transcribe_audio(self):
        if not self.audio_frames:
            self.root.after(0, lambda: self._set_status("ready", "No audio captured"))
            self.root.after(0, lambda: self.record_btn.set_enabled(True))
            return

        audio = np.concatenate(self.audio_frames)

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=TEMP_FILE_PREFIX, suffix=".wav", delete=False
            ) as f:
                temp_path = f.name
                self._temp_files.add(temp_path)

            with wave.open(temp_path, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                audio_int16 = (audio * 32767).astype(np.int16)
                wf.writeframes(audio_int16.tobytes())

            segments, info = self.model.transcribe(
                temp_path, beam_size=5, language=self._selected_language
            )
            text = " ".join(seg.text for seg in segments).strip()

            if text:
                self.root.after(0, lambda t=text: self._on_transcription_done(t))
            else:
                self.root.after(0, lambda: self._set_status("ready", "No speech detected"))
        except Exception as e:
            self.root.after(0, lambda: self._set_status("error", f"Transcription error: {e}"))
        finally:
            if temp_path:
                try:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                    self._temp_files.discard(temp_path)
                except OSError:
                    pass
            self.root.after(0, lambda: self.record_btn.set_enabled(True))

    def _on_transcription_done(self, text):
        self._hide_placeholder()

        if self.append_var.get():
            current = self.text_area.get("1.0", tk.END).strip()
            if current:
                self.text_area.insert(tk.END, "\n\n" + text)
            else:
                self.text_area.insert(tk.END, text)
        else:
            self.text_area.delete("1.0", tk.END)
            self.text_area.insert(tk.END, text)

        full_text = self.text_area.get("1.0", tk.END).strip()
        clipboard_msg = ""
        if CLIPBOARD_AVAILABLE:
            try:
                pyperclip.copy(full_text)
                clipboard_msg = " \u2014 copied!"
            except Exception:
                pass

        self._set_status("ready", f"Done{clipboard_msg}")

        timestamp = time.strftime("%H:%M")
        preview = text[:65] + "..." if len(text) > 65 else text
        self.history.insert(0, text)
        self.history_chars += len(text)
        self.history_listbox.insert(0, f"{timestamp}  {preview}")
        self._trim_history()

    # ── Clipboard / Clear ────────────────────────────────────────────────

    def _copy_to_clipboard(self):
        text = self.text_area.get("1.0", tk.END).strip()
        if not text or getattr(self, "_placeholder_visible", False):
            self._set_status("ready", "Nothing to copy")
            return
        if CLIPBOARD_AVAILABLE:
            try:
                pyperclip.copy(text)
                self._set_status("ready", "Copied to clipboard!")
            except Exception:
                self._set_status("error", "Clipboard failed")
        else:
            self._set_status("error", "pyperclip not installed")

    def _clear_text(self):
        self.text_area.delete("1.0", tk.END)
        self._show_placeholder()
        self._set_status("ready", "Cleared")

    # ── History ──────────────────────────────────────────────────────────

    def _trim_history(self):
        while len(self.history) > MAX_HISTORY_ITEMS or self.history_chars > MAX_HISTORY_CHARS:
            if not self.history:
                break
            removed = self.history.pop()
            self.history_chars -= len(removed)
            self.history_listbox.delete(len(self.history))

    def _on_history_select(self, event):
        sel = self.history_listbox.curselection()
        if sel:
            idx = sel[0]
            text = self.history[idx]
            self._hide_placeholder()
            self.text_area.delete("1.0", tk.END)
            self.text_area.insert(tk.END, text)

    # ── Status ───────────────────────────────────────────────────────────

    def _set_status(self, state, message):
        c = self.theme.c
        dot_colors = {
            "loading": c("warning"),
            "ready": c("success"),
            "recording": c("record"),
            "error": c("record"),
            "warning": c("warning"),
        }
        self.status_dot.config(fg=dot_colors.get(state, c("text_secondary")))
        self.status_label.config(text=f"  {message}")

    # ── Keyboard ─────────────────────────────────────────────────────────

    def _on_space(self, event):
        if event.widget != self.text_area:
            if self.is_recording and not self.is_paused:
                self._pause_recording()
            elif self.is_paused:
                self._resume_recording()
            elif not self.is_recording:
                self._start_recording()
            return "break"

    def _on_text_key(self, event):
        self._hide_placeholder()

    # ── Privacy Notice ───────────────────────────────────────────────────

    def _show_privacy_notice_if_needed(self):
        # Store consent in user's home directory so it persists across
        # app rebuilds and .app bundle recreations
        config_dir = os.path.join(os.path.expanduser("~"), ".voicescribe")
        consent_file = os.path.join(config_dir, "privacy_accepted")

        if os.path.exists(consent_file):
            return

        accepted = messagebox.askokcancel(
            "Privacy & Data Handling", PRIVACY_NOTICE, icon="info"
        )

        if accepted:
            try:
                os.makedirs(config_dir, exist_ok=True)
                with open(consent_file, "w") as f:
                    f.write(f"accepted={time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
                    f.write(f"version={APP_VERSION}\n")
            except OSError:
                pass
        else:
            self.root.destroy()
            sys.exit(0)

    # ── Cleanup & Exit ───────────────────────────────────────────────────

    def _on_close(self):
        if self._closing:
            return
        self._closing = True
        self.logger.info("Shutting down...")

        if self.is_recording:
            self.is_recording = False
            if self.stream:
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None

        # Stop Ollama if we started it
        self.ollama.stop()

        self._cleanup()

        try:
            self.root.destroy()
        except Exception:
            pass

    def _cleanup(self):
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

        for path in list(self._temp_files):
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except OSError:
                pass
        self._temp_files.clear()

        try:
            tmp_dir = tempfile.gettempdir()
            for f in glob.glob(os.path.join(tmp_dir, f"{TEMP_FILE_PREFIX}*.wav")):
                try:
                    os.unlink(f)
                except OSError:
                    pass
        except Exception:
            pass

        self.model = None
        self.history.clear()
        self.audio_frames.clear()
        self.logger.info("Cleanup complete")


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    app = VoiceScribe(root)
    root.mainloop()


if __name__ == "__main__":
    main()
