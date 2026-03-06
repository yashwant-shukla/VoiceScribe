#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# VoiceScribe — macOS .app Bundle Builder (Fully Offline)
#
# Creates a self-contained VoiceScribe.app that includes:
#   • All Python package wheels (offline pip install)
#   • Ollama binary (AI engine)
#   • llama3.2 model (text polish)
#   • Whisper base model (speech recognition)
#
# After building, no internet connection is needed to run the app.
#
# Usage:  chmod +x create_app.sh && ./create_app.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="VoiceScribe"
APP_DIR="$SCRIPT_DIR/$APP_NAME.app"
INSTALL_DIR="/Applications/$APP_NAME.app"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   VoiceScribe — Offline App Builder          ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Check prerequisites ──────────────────────────────────────────────────────

echo "Checking prerequisites..."

# Check for Python 3
if command -v python3 &>/dev/null; then
    PYTHON_PATH="$(command -v python3)"
    PYTHON_VERSION="$(python3 --version 2>&1)"
    echo "  ✓ $PYTHON_VERSION found at $PYTHON_PATH"
else
    echo "  ✗ Python 3 not found. Install from https://www.python.org/downloads/"
    exit 1
fi

# Check for pip
if python3 -m pip --version &>/dev/null; then
    echo "  ✓ pip available"
else
    echo "  ✗ pip not found. Install: python3 -m ensurepip"
    exit 1
fi

# Check for Homebrew
if ! command -v brew &>/dev/null; then
    echo "  ✗ Homebrew not found. Install from https://brew.sh"
    exit 1
fi
echo "  ✓ Homebrew available"

# Check/install PortAudio
if brew list portaudio &>/dev/null 2>&1; then
    echo "  ✓ portaudio installed"
else
    echo "  ⟳ Installing portaudio via Homebrew..."
    brew install portaudio
    echo "  ✓ portaudio installed"
fi

# Check for Ollama (required for bundling)
OLLAMA_BIN=""
if command -v ollama &>/dev/null; then
    OLLAMA_BIN="$(command -v ollama)"
elif [ -x "/opt/homebrew/bin/ollama" ]; then
    OLLAMA_BIN="/opt/homebrew/bin/ollama"
elif [ -x "/usr/local/bin/ollama" ]; then
    OLLAMA_BIN="/usr/local/bin/ollama"
fi

if [ -z "$OLLAMA_BIN" ]; then
    echo "  ✗ Ollama not found. Install it first:"
    echo "    brew install ollama"
    exit 1
fi
echo "  ✓ Ollama found at $OLLAMA_BIN"

echo ""

# ── Create virtual environment & install deps ────────────────────────────────

VENV_DIR="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "  ✓ Virtual environment created at .venv/"
else
    echo "  ✓ Virtual environment already exists"
fi

echo "Installing/updating dependencies..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"
echo "  ✓ All dependencies installed"

echo ""

# ── Generate icon if missing ─────────────────────────────────────────────────

ICON_PATH="$SCRIPT_DIR/icon.icns"
if [ ! -f "$ICON_PATH" ]; then
    echo "Generating app icon..."
    "$VENV_DIR/bin/python" "$SCRIPT_DIR/generate_icon.py"
    echo "  ✓ Icon generated"
else
    echo "  ✓ Icon found"
fi

echo ""

# ── Download & cache all bundled resources ───────────────────────────────────

echo "Preparing offline bundle..."
echo "  (This may take a while on first run — downloading models)"
echo ""

# 1. Generate pip wheels
WHEELS_DIR="$SCRIPT_DIR/.build_wheels"
echo "  Downloading pip wheels..."
rm -rf "$WHEELS_DIR"
mkdir -p "$WHEELS_DIR"
"$VENV_DIR/bin/pip" wheel -r "$SCRIPT_DIR/requirements.txt" -w "$WHEELS_DIR" --quiet 2>/dev/null
WHEEL_COUNT=$(ls -1 "$WHEELS_DIR"/*.whl 2>/dev/null | wc -l | tr -d ' ')
echo "  ✓ $WHEEL_COUNT wheel files cached"

# 2. Pre-cache Whisper base model
WHISPER_CACHE="$SCRIPT_DIR/.build_whisper_cache"
echo "  Downloading Whisper base model (~150 MB)..."
if [ -d "$WHISPER_CACHE" ] && [ "$(ls -A "$WHISPER_CACHE" 2>/dev/null)" ]; then
    echo "  ✓ Whisper model already cached"
else
    rm -rf "$WHISPER_CACHE"
    mkdir -p "$WHISPER_CACHE"
    HF_HUB_CACHE="$WHISPER_CACHE" "$VENV_DIR/bin/python" -c "
from faster_whisper import WhisperModel
print('  Downloading and loading Whisper base model...')
model = WhisperModel('base', device='cpu', compute_type='int8')
print('  ✓ Whisper base model cached')
"
fi

# 3. Prepare Ollama model directory
OLLAMA_MODELS_DIR="$SCRIPT_DIR/.build_ollama_models"
echo "  Downloading llama3.2 model (~2 GB)..."

if [ -d "$OLLAMA_MODELS_DIR/manifests" ] && [ -d "$OLLAMA_MODELS_DIR/blobs" ]; then
    echo "  ✓ llama3.2 model already cached"
else
    rm -rf "$OLLAMA_MODELS_DIR"
    mkdir -p "$OLLAMA_MODELS_DIR"

    # Start a temporary Ollama server with our bundled models dir
    OLLAMA_MODELS="$OLLAMA_MODELS_DIR" "$OLLAMA_BIN" serve &>/dev/null &
    TEMP_OLLAMA_PID=$!
    echo "  Started temporary Ollama server (PID $TEMP_OLLAMA_PID)..."

    # Wait for server to come up
    for i in $(seq 1 30); do
        if curl -s --max-time 2 http://localhost:11434/api/tags &>/dev/null; then
            break
        fi
        sleep 1
    done

    # Pull the model
    echo "  Pulling llama3.2 (this may take several minutes)..."
    "$OLLAMA_BIN" pull llama3.2

    # Verify the model was pulled
    MODEL_CHECK=$(curl -s http://localhost:11434/api/tags 2>/dev/null)
    if echo "$MODEL_CHECK" | grep -q "llama3.2"; then
        echo "  ✓ llama3.2 model cached"
    else
        echo "  ⚠ Model pull may have failed — check logs"
    fi

    # Stop temporary server
    kill "$TEMP_OLLAMA_PID" 2>/dev/null || true
    wait "$TEMP_OLLAMA_PID" 2>/dev/null || true
    echo "  Stopped temporary Ollama server"
fi

echo ""

# ── Build .app bundle ────────────────────────────────────────────────────────

echo "Building $APP_NAME.app..."

# Clean any existing build
rm -rf "$APP_DIR"

# Create directory structure
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"
mkdir -p "$APP_DIR/Contents/Resources/wheels"
mkdir -p "$APP_DIR/Contents/Resources/ollama/bin"
mkdir -p "$APP_DIR/Contents/Resources/ollama/models"
mkdir -p "$APP_DIR/Contents/Resources/whisper-models"

# Copy icon
cp "$ICON_PATH" "$APP_DIR/Contents/Resources/AppIcon.icns"

# Copy bundled resources
echo "  Copying pip wheels..."
cp "$WHEELS_DIR"/*.whl "$APP_DIR/Contents/Resources/wheels/"

echo "  Copying Ollama binary..."
cp "$OLLAMA_BIN" "$APP_DIR/Contents/Resources/ollama/bin/ollama"
chmod +x "$APP_DIR/Contents/Resources/ollama/bin/ollama"

echo "  Copying Ollama models..."
cp -R "$OLLAMA_MODELS_DIR"/* "$APP_DIR/Contents/Resources/ollama/models/"

echo "  Copying Whisper models..."
cp -R "$WHISPER_CACHE"/* "$APP_DIR/Contents/Resources/whisper-models/"

# Calculate bundle size
BUNDLE_SIZE=$(du -sh "$APP_DIR/Contents/Resources" 2>/dev/null | cut -f1)
echo "  ✓ Resources bundled ($BUNDLE_SIZE)"

# ── Create Info.plist ────────────────────────────────────────────────────────

cat > "$APP_DIR/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>VoiceScribe</string>
    <key>CFBundleDisplayName</key>
    <string>VoiceScribe</string>
    <key>CFBundleIdentifier</key>
    <string>com.voicescribe.app</string>
    <key>CFBundleVersion</key>
    <string>2.0.0</string>
    <key>CFBundleShortVersionString</key>
    <string>2.0.0</string>
    <key>CFBundleExecutable</key>
    <string>launch</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSMicrophoneUsageDescription</key>
    <string>VoiceScribe needs microphone access to transcribe your voice.</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
</dict>
</plist>
PLIST

# ── Create the launcher script ───────────────────────────────────────────────
# This runs when you double-click the app.
# It sets up env vars pointing to bundled resources, creates venv from
# bundled wheels if needed, and launches the bootstrapper.

cat > "$APP_DIR/Contents/MacOS/launch" << LAUNCHER
#!/bin/bash
# VoiceScribe Launcher — Fully Offline
# All resources (pip wheels, Ollama, models) are bundled in Resources/

# Resolve paths
LAUNCH_DIR="\$(cd "\$(dirname "\$0")" && pwd)"
APP_RESOURCES="\$(cd "\$LAUNCH_DIR/../Resources" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
VENV_DIR="\$PROJECT_DIR/.venv"
LOG_FILE="\$PROJECT_DIR/.voicescribe.log"

# ── Fix PATH for macOS .app bundles ─────────────────────────────────────
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:\$PATH"

# ── Set bundled resource paths ──────────────────────────────────────────
export VOICESCRIBE_BUNDLED_OLLAMA="\$APP_RESOURCES/ollama/bin/ollama"
export OLLAMA_MODELS="\$APP_RESOURCES/ollama/models"
export HF_HUB_CACHE="\$APP_RESOURCES/whisper-models"
export VOICESCRIBE_WHEELS="\$APP_RESOURCES/wheels"
export VOICESCRIBE_VENV="\$VENV_DIR"
export VOICESCRIBE_PROJECT="\$PROJECT_DIR"

# ── Redirect output to log file ────────────────────────────────────────
exec > "\$LOG_FILE" 2>&1
echo "=== VoiceScribe Launch: \$(date) ==="
echo "Project dir: \$PROJECT_DIR"
echo "App resources: \$APP_RESOURCES"
echo "Bundled Ollama: \$VOICESCRIBE_BUNDLED_OLLAMA"
echo "Ollama models: \$OLLAMA_MODELS"
echo "HF cache: \$HF_HUB_CACHE"
echo "Wheels dir: \$VOICESCRIBE_WHEELS"
echo "PATH: \$PATH"

# ── Ensure virtual environment exists ──────────────────────────────────
if [ ! -d "\$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "\$VENV_DIR"
fi

PYTHON="\$VENV_DIR/bin/python"

# ── Launch via Bootstrapper ────────────────────────────────────────────
echo "Launching VoiceScribe bootstrapper..."
cd "\$PROJECT_DIR"
exec "\$PYTHON" "\$PROJECT_DIR/voicescribe_bootstrap.py"
LAUNCHER

chmod +x "$APP_DIR/Contents/MacOS/launch"

echo "  ✓ App bundle created at $APP_DIR"

echo ""

# ── Install to /Applications ─────────────────────────────────────────────────

echo "Would you like to install VoiceScribe to /Applications? (y/n)"
read -r REPLY

if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    if [ -d "$INSTALL_DIR" ]; then
        echo "  Removing old installation..."
        rm -rf "$INSTALL_DIR"
    fi
    cp -R "$APP_DIR" "$INSTALL_DIR"
    echo "  ✓ Installed to /Applications/VoiceScribe.app"
    echo ""
    echo "  You can now find VoiceScribe in:"
    echo "    • Launchpad"
    echo "    • Spotlight (Cmd+Space → VoiceScribe)"
    echo "    • /Applications folder"
    echo ""
    echo "  Tip: Right-click the app in Dock → Options → Keep in Dock"
else
    echo "  Skipped. You can launch from: $APP_DIR"
    echo "  Or drag VoiceScribe.app to /Applications manually."
fi

echo ""
echo "═══════════════════════════════════════════════"
echo "  ✓ VoiceScribe is ready!"
echo ""
echo "  This is a fully offline bundle. Everything"
echo "  needed is included:"
echo "    • Whisper base model (transcription)"
echo "    • Ollama + llama3.2 (AI text polish)"
echo "    • All Python packages ($WHEEL_COUNT wheels)"
echo ""
echo "  No internet connection needed to run!"
echo "═══════════════════════════════════════════════"
echo ""
