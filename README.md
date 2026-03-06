# VoiceScribe

Free, fully offline voice-to-text transcription with AI text polishing. Runs entirely on your machine — no API keys, no internet, no cost.

Speak → get text → polish into a clean prompt → paste into Claude or anywhere.

---

## Quick Start (macOS)

```bash
git clone https://github.com/yashwant-shukla/VoiceScribe.git
cd VoiceScribe
chmod +x create_app.sh
./create_app.sh
```

This builds a fully self-contained **VoiceScribe.app** (~2.5 GB) with everything bundled:

- Whisper base model (speech-to-text)
- Ollama + llama3.2 (AI text polish)
- All Python packages (38 wheels)
- No internet needed after build

The build script will install prerequisites (Homebrew's `portaudio` and `ollama`), download all models, and package everything into a `.app` bundle. Optionally installs to `/Applications`.

After setup, launch from **Launchpad**, **Spotlight** (Cmd+Space → VoiceScribe), or the **Dock**.

---

## How to Use

1. **Click the red Record button** (or press **Space**) to start recording
2. **Speak** your thoughts
3. **Click Pause** to temporarily stop, or **Stop** to finish
4. Your text appears and is **auto-copied to clipboard**
5. Click **Polish Text** to clean up filler words and structure the text
6. **Paste** (Cmd+V) into claude.ai, a text editor, or wherever

### Controls

- **Record** (red circle) — start or resume recording
- **Pause** (two bars) — pause recording, keep audio buffer
- **Stop** (square) — finish recording, begin transcription
- **Copy** (clipboard icon) — copy text to clipboard
- **Clear** (X icon) — clear the text area
- **Polish Text** — refine raw speech into polished text using the bundled AI model
- **Append** — keep adding to the same text across recordings

### Settings Panel

Click **⚙ Settings** to expand:

- **Microphone** — select which input device to use (built-in, Bluetooth, USB). Refreshes automatically every 30 seconds and has a manual refresh button.
- **Transcription Accuracy** — choose between Fast, Balanced, High, or Best.
- **AI Polish Model** — select which Ollama model to use.
- **AI Engine (Ollama)** — start or stop the bundled AI engine.

### Theme Switching

Click the theme button in the top-right corner to cycle between light, dark, and auto (follows system).

---

## How AI Polish Works

**Raw voice:** "so um I have this bug where like the login page just shows a blank screen and I think it might be a React rendering issue"

**After polish:** "I have a bug where the login page shows a blank screen. I suspect it may be a React rendering issue. Can you help debug this?"

Removes filler words, fixes grammar, adds structure — never adds information you didn't say. All processing happens locally on your machine.

---

## Transcription Accuracy Levels

| Setting   | Whisper Model | Size    | Speed   | Accuracy |
|-----------|---------------|---------|---------|----------|
| Fast      | tiny          | ~75 MB  | Fastest | Basic    |
| Balanced  | base          | ~150 MB | Fast    | Good (default) |
| High      | small         | ~500 MB | Medium  | Better   |
| Best      | medium        | ~1.5 GB | Slow    | Best     |

Change accuracy anytime from the Settings panel. New models download automatically on first use.

---

## Development Setup

For running directly without building the `.app`:

```bash
cd VoiceScribe
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
brew install portaudio ollama
ollama pull llama3.2
python voicescribe.py
```

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Space    | Start/Pause/Resume recording (when not typing in text area) |

---

## Troubleshooting

**"Mic error" on record:**
macOS: System Settings → Privacy & Security → Microphone → enable for Terminal/VoiceScribe.

**App won't open (macOS Gatekeeper):**
Right-click the app → Open → click Open in the dialog. Needed only once.

**Wrong microphone active:**
Open Settings → Microphone dropdown → select the correct input device. Click ↻ to refresh if a device was just connected.

**Low accuracy:**
Switch to "High" or "Best" accuracy in Settings. Speak clearly and minimize background noise.

---

## Project Structure

```
VoiceScribe/
├── voicescribe.py              # Main application
├── voicescribe_bootstrap.py    # Dependency checker & installer
├── create_app.sh               # Offline .app builder (downloads & bundles everything)
├── generate_icon.py            # App icon generator
├── icon.icns                   # Generated app icon
├── requirements.txt            # Python dependencies
└── README.md
```

---

## Privacy

Everything runs 100% offline. No analytics, no telemetry, no network calls. Audio is processed locally and never stored on disk. See the in-app privacy notice for full details.

---

## License

MIT — use it however you like.
