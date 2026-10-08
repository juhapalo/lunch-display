#!/bin/sh
# Starts a full-screen browser without any window frames, toolbars or cursor.
# Run as an X client, e.g.:  startx /path/to/deploy/kiosk.sh -- -nocursor
#
# Environment variables:
#   LUNCH_DISPLAY_URL      page to show (default http://localhost:8080/)
#   LUNCH_DISPLAY_BROWSER  surf (default, lightest) or chromium / chromium-browser

URL="${LUNCH_DISPLAY_URL:-http://localhost:8080/}"
BROWSER="${LUNCH_DISPLAY_BROWSER:-surf}"

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
        chromium|chromium-browser)
            "$BROWSER" --kiosk --noerrdialogs --disable-infobars --incognito \
                --disable-session-crashed-bubble --check-for-update-interval=31536000 \
                "$URL"
            ;;
        *)
            surf "$URL"
            ;;
    esac
    sleep 2
done
