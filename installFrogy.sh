#!/usr/bin/env bash

set -e

echo "Installing Desktop Frog..."

# ----------------------------
# CONFIG (CHANGE THIS)
# ----------------------------
REPO_URL="https://github.com/Royal-Sproket/Frogy.git"
INSTALL_DIR="$HOME/.desktop-frog"
VENV_DIR="$INSTALL_DIR/venv"

# ----------------------------
# Clone repo
# ----------------------------
echo "Cloning repository..."
rm -rf "$INSTALL_DIR"
git clone "$REPO_URL" "$INSTALL_DIR"

# ----------------------------
# Create virtual environment
# ----------------------------
echo "Creating virtual environment..."
python3 -m venv "$VENV_DIR"

# ----------------------------
# Activate and install deps
# ----------------------------
echo "Installing dependencies..."
source "$VENV_DIR/bin/activate"

pip install --upgrade pip
pip install PyQt6 python-xlib psutil

# optional but recommended
sudo apt install -y wmctrl libxcb-cursor0

deactivate

# ----------------------------
# Create launcher script
# ----------------------------
echo "Creating launcher..."

LAUNCHER="$INSTALL_DIR/run.sh"

cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
source "$VENV_DIR/bin/activate"
python3 "$INSTALL_DIR/frogy.py" "\$@"
EOF

chmod +x "$LAUNCHER"

# ----------------------------
# Desktop shortcut
# ----------------------------
echo "Creating desktop shortcut..."

DESKTOP_FILE="$HOME/.local/share/applications/desktop-frog.desktop"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Name=Desktop Frog
Comment=Chaotic window-eating frog
Exec=$LAUNCHER --wander
Icon=utilities-terminal
Terminal=false
Type=Application
Categories=Utility;
EOF

chmod +x "$DESKTOP_FILE"

# optional: add shortcut to desktop
cp "$DESKTOP_FILE" "$HOME/Desktop/" 2>/dev/null || true

echo "Creating global command 'frogy'..."

sudo ln -sf "$LAUNCHER" /usr/local/bin/frogy


echo ""
echo "Installation complete!"
echo ""
echo "Run it with:"
echo "  desktop-frog --eat firefox"
echo ""
echo "Or launch from your app menu: frogy"

