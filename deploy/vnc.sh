#!/bin/sh
# Shares the kiosk's X display (:0) over VNC with x11vnc.
# Started by lunch-display-vnc.service; the port and password come from
# vnc_port and vnc_password in config.json.

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="${RUNTIME_DIRECTORY:-}"
if [ -z "$RUN_DIR" ]; then
    RUN_DIR="$(mktemp -d)" || exit 1
fi
PASSWORD_FILE="$RUN_DIR/vnc-password"

# Exit status 78 (configuration error) stops systemd from restarting.
if ! VNC_PORT="$(python3 "$APP_DIR/deploy/kiosk_config.py" vnc-prepare "$PASSWORD_FILE")"; then
    exit 78
fi
if [ "$VNC_PORT" = "disabled" ]; then
    exit 0
fi

# The password is passed in a private file (removed once read), never on the
# command line. Until X is running x11vnc exits and systemd retries.
exec x11vnc -display :0 -auth "$HOME/.Xauthority" -forever -shared \
    -rfbport "$VNC_PORT" -passwdfile "rm:$PASSWORD_FILE" -noxdamage
