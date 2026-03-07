#!/usr/bin/env bash
# install.sh — Installs YouTube AI Agent using uv (fast, no resolver errors)
# uv is 10-100x faster than pip and handles deep dependency graphs easily.
#
# Usage: chmod +x install.sh && ./install.sh

set -e

echo ""
echo "🎬 YouTube AI Agent — Installation"
echo "===================================="
echo ""

# ── 1. Install uv (the modern Python package manager) ────────────────────────
if ! command -v uv &> /dev/null; then
    echo "▶  Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Add uv to PATH for the rest of this script
    export PATH="$HOME/.local/bin:$PATH"
    export PATH="$HOME/.cargo/bin:$PATH"
else
    echo "▶  uv already installed: $(uv --version)"
fi

echo ""

# ── 2. Create virtual environment ────────────────────────────────────────────
if [ ! -d ".venv" ]; then
    echo "▶  Creating virtual environment..."
    uv venv .venv --python 3.11
else
    echo "▶  Virtual environment already exists"
fi

# Activate
source .venv/bin/activate

echo ""

# ── 3. Install PyTorch CPU build ─────────────────────────────────────────────
echo "▶  Installing PyTorch (CPU build)..."
uv pip install torch==2.1.2 torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cpu

echo ""

# ── 4. Install faster-whisper ────────────────────────────────────────────────
echo "▶  Installing faster-whisper..."
uv pip install "faster-whisper>=1.0.0,<2.0.0"
uv pip install "onnxruntime>=1.17.0"

echo ""

# ── 5. Install all project dependencies ──────────────────────────────────────
echo "▶  Installing project dependencies..."
uv pip install -r requirements.txt

echo ""

# ── 6. Install project in editable mode ──────────────────────────────────────
echo "▶  Installing project in editable mode..."
uv pip install -e .

echo ""

# ── 7. Pre-download Kokoro TTS weights ───────────────────────────────────────
echo "▶  Pre-downloading Kokoro TTS weights (one-time ~500 MB)..."
python -c "
try:
    from kokoro import KPipeline
    KPipeline(lang_code='a')
    print('   Kokoro ready ✅')
except Exception as e:
    print(f'   Kokoro skipped ({e})')
    print('   gTTS fallback will be used automatically')
"

echo ""
echo "===================================="
echo "✅  Installation complete!"
echo ""
echo "Your virtual environment is at .venv/"
echo "It is already activated for this session."
echo "Next time, activate it with:"
echo "   source .venv/bin/activate   (macOS/Linux)"
echo "   .venv\\Scripts\\activate       (Windows)"
echo ""
echo "Next steps:"
echo "  1. cp .env.example .env"
echo "  2. Add your API keys to .env"
echo "  3. python setup_youtube_auth.py"
echo "  4. python main.py plan --topic \"Personal Finance for Beginners\""
echo ""
