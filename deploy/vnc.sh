#!/bin/sh
# Shares the kiosk's X display (:0) over VNC with x11vnc.
# Started by lunch-display-vnc.service; the port and password come from
# vnc_port and vnc_password in config.json.

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# Private (0700) runtime directory: RuntimeDirectory= of the service, or the
# user's XDG runtime directory when run by hand.
RUN_DIR="${RUNTIME_DIRECTORY:-${XDG_RUNTIME_DIR:-}}"
if [ -z "$RUN_DIR" ] || [ ! -d "$RUN_DIR" ]; then
    echo "lunch-display vnc: RUNTIME_DIRECTORY or XDG_RUNTIME_DIR must be set" >&2
    exit 78
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
