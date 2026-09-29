#!/usr/bin/env bash
# SetuCode Installation Script for Linux/macOS

set -e

echo "================================================="
echo "    Installing SetuCode Globally (Linux/macOS)   "
echo "================================================="

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "[!] 'uv' not found. Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

# Ensure project dependencies are synced
echo "Syncing dependencies with uv..."
uv sync

# Path to the uv executable environments
VENV_PYTHON="$(pwd)/.venv/bin/python"
TARGET_BIN="/usr/local/bin/setucode"
LOCAL_BIN="$HOME/.local/bin/setucode"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "[!] Virtual environment not found at $VENV_PYTHON"
    exit 1
fi

# Try to install to /usr/local/bin first (requires sudo)
if [ -w "/usr/local/bin" ]; then
    BIN_PATH="$TARGET_BIN"
else
    echo "[i] No write access to /usr/local/bin. Installing to $HOME/.local/bin instead."
    mkdir -p "$HOME/.local/bin"
    BIN_PATH="$LOCAL_BIN"
fi

# Create launch script
cat <<EOF > "$BIN_PATH"
#!/usr/bin/env bash
# SetuCode Launcher
export WORKSPACE_ROOT="\$(pwd)"
cd "$(pwd)" || exit 1
exec "$VENV_PYTHON" -m dashboard.app "\$@"
EOF

chmod +x "$BIN_PATH"

echo ""
echo "✓ SetuCode installed successfully!"
echo "  Location: $BIN_PATH"
echo ""
echo "You can now run 'setucode' from any directory in your terminal."
echo "Note: If you installed to $HOME/.local/bin, make sure it is in your PATH."
