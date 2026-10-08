#!/bin/sh
# Installs the lunch display on Raspberry Pi OS (Lite, 32-bit) on a Pi 1B.
# Run from the repository directory as the user that should own the display:
#   ./deploy/install.sh
set -eu

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="$(id -un)"

echo "Installing packages..."
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    python3 curl \
    xserver-xorg xinit x11-xserver-utils \
    matchbox-window-manager unclutter surf \
    fonts-dejavu-core fonts-noto-color-emoji

if [ ! -f "$APP_DIR/config.json" ]; then
    cp "$APP_DIR/config.example.json" "$APP_DIR/config.json"
    echo "Created $APP_DIR/config.json"
fi

echo "Installing systemd service..."
sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@USER@|$RUN_USER|g" \
    "$APP_DIR/deploy/lunch-display.service" | sudo tee /etc/systemd/system/lunch-display.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now lunch-display.service

echo "Enabling console auto-login and kiosk start..."
if command -v raspi-config >/dev/null 2>&1; then
    sudo raspi-config nonint do_boot_behaviour B2
fi
chmod +x "$APP_DIR/deploy/kiosk.sh"
PROFILE="$HOME/.bash_profile"
MARKER="# lunch-display kiosk"
if ! grep -q "$MARKER" "$PROFILE" 2>/dev/null; then
    cat >> "$PROFILE" <<EOF
$MARKER
if [ -z "\${DISPLAY:-}" ] && [ "\$(tty)" = "/dev/tty1" ]; then
    exec startx "$APP_DIR/deploy/kiosk.sh" -- -nocursor
fi
EOF
fi

echo "Done. Reboot to start the display: sudo reboot"
