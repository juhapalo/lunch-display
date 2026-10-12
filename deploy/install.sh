#!/bin/sh
# Installs the lunch display on Raspberry Pi OS (Lite, 32-bit) on a Pi 1B.
# Run from the repository directory as the user that should own the display:
#   ./deploy/install.sh
set -eu

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="$(id -un)"

if [ ! -e "$APP_DIR/config.json" ] && [ ! -L "$APP_DIR/config.json" ]; then
    cp "$APP_DIR/config.example.json" "$APP_DIR/config.json"
    echo "Created $APP_DIR/config.json"
fi

FRONTEND_BROWSER_ENABLED="$(python3 "$APP_DIR/deploy/kiosk_config.py" browser-enabled)"

echo "Installing packages..."
sudo apt-get update
sudo apt-get install -y --no-install-recommends python3 curl
if [ "$FRONTEND_BROWSER_ENABLED" = "true" ]; then
    sudo apt-get install -y --no-install-recommends \
        xserver-xorg xinit x11-xserver-utils \
        matchbox-window-manager unclutter surf \
        fonts-dejavu-core fonts-noto-color-emoji
fi

echo "Installing systemd service..."
sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@USER@|$RUN_USER|g" \
    "$APP_DIR/deploy/lunch-display.service" | sudo tee /etc/systemd/system/lunch-display.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now lunch-display.service

if [ "$FRONTEND_BROWSER_ENABLED" = "true" ]; then
    echo "Enabling console auto-login and kiosk start..."
    if command -v raspi-config >/dev/null 2>&1; then
        sudo raspi-config nonint do_boot_behaviour B2
    fi
else
    echo "Local browser disabled; installing the web service only."
fi
chmod +x "$APP_DIR/deploy/kiosk.sh"
PROFILE="$HOME/.bash_profile"
python3 "$APP_DIR/deploy/kiosk_config.py" install-profile "$PROFILE"

echo "Done. Reboot to start the display: sudo reboot"
