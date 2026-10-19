#!/bin/sh
# Starts a full-screen Chromium without any window frames, toolbars or cursor.
# Run as an X client, e.g.:  startx /path/to/deploy/kiosk.sh -- -nocursor
#
# The lunch-display service opens every rotation page in its own tab and
# switches between them over the Chrome DevTools Protocol (port 9222, local
# connections only), so the pages are not reloaded at every page change.
#
# Environment variables:
#   LUNCH_DISPLAY_URL             first page to show
#                                 (default http://localhost:8080/dashboard)
#   LUNCH_DISPLAY_BROWSER         chromium-browser or chromium (default: whichever
#                                 is installed); surf is a fallback that shows the
#                                 iframe rotation page http://localhost:8080/
#   LUNCH_DISPLAY_CHROMIUM_FLAGS  extra Chromium command line flags

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if ! FRONTEND_BROWSER_ENABLED="$(python3 "$APP_DIR/deploy/kiosk_config.py" browser-enabled)"; then
    exit 1
fi
if [ "$FRONTEND_BROWSER_ENABLED" = "false" ]; then
    exit 0
fi

BROWSER="${LUNCH_DISPLAY_BROWSER:-}"
if [ -z "$BROWSER" ]; then
    for candidate in chromium-browser chromium; do
        if command -v "$candidate" >/dev/null 2>&1; then
            BROWSER="$candidate"
            break
        fi
    done
    BROWSER="${BROWSER:-chromium-browser}"
fi
if [ "$BROWSER" = "surf" ]; then
    URL="${LUNCH_DISPLAY_URL:-http://localhost:8080/}"
else
    URL="${LUNCH_DISPLAY_URL:-http://localhost:8080/dashboard}"
fi
PROFILE_DIR="$HOME/.config/lunch-display-chromium"

# Never blank the screen.
xset s off
xset s noblank
xset -dpms

# Hide the mouse pointer.
if command -v unclutter >/dev/null 2>&1; then
    unclutter -idle 1 -root &
fi

# Window manager that maximises every window and draws no title bars.
matchbox-window-manager -use_titlebar no -use_cursor no &

# Wait for the local server to come up.
until curl -fs -o /dev/null "$URL"; do
    sleep 2
done

# Restart the browser if it ever exits or crashes.
while true; do
    case "$BROWSER" in
        surf)
            surf "$URL"
            ;;
        *)
            # Mark the previous run as cleanly exited so that no "restore
            # pages" prompt is shown after a crash or power cut.
            if [ -f "$PROFILE_DIR/Default/Preferences" ]; then
                sed -i -e 's/"exited_cleanly":false/"exited_cleanly":true/' \
                    -e 's/"exit_type":"[^"]*"/"exit_type":"Normal"/' \
                    "$PROFILE_DIR/Default/Preferences"
            fi
            # shellcheck disable=SC2086
            "$BROWSER" --kiosk --noerrdialogs --disable-infobars \
                --disable-session-crashed-bubble --check-for-update-interval=31536000 \
                --no-first-run --password-store=basic --disable-sync \
                --disable-background-networking --disable-component-update \
                --disable-features=Translate,MediaRouter \
                --enable-low-end-device-mode --disable-gpu \
                --disable-smooth-scrolling --disable-low-res-tiling \
                --disable-composited-antialiasing --disk-cache-size=33554432 \
                --user-data-dir="$PROFILE_DIR" --remote-debugging-port=9222 \
                ${LUNCH_DISPLAY_CHROMIUM_FLAGS:-} \
                "$URL"
            ;;
    esac
    sleep 2
done
