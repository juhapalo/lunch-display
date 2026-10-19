#!/usr/bin/env python3
"""Check kiosk/VNC configuration and maintain the managed login-profile block."""

import json
import os
from pathlib import Path
import re
import shlex
import sys

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from lunch_display.config import (
    DEFAULT_VNC_PORT,
    validate_frontend_browser_enabled,
    validate_vnc_settings,
)


MARKER = "# lunch-display kiosk"
END_MARKER = "# end lunch-display kiosk"
LEGACY_BLOCK = re.compile(
    r'^# lunch-display kiosk\n'
    r'if \[ -z "\$\{DISPLAY:-\}" \] && \[ "\$\(tty\)" = "/dev/tty1" \]; then\n'
    r'    exec startx "[^"\n]*/deploy/kiosk\.sh" -- -nocursor\n'
    r'fi(?:\n|$)',
    re.MULTILINE,
)
MANAGED_BLOCK = re.compile(
    r'^# lunch-display kiosk\n'
    r'if \[ -z "\$\{DISPLAY:-\}" \] && \[ "\$\(tty\)" = "/dev/tty1" \]; then\n'
    r'    if lunch_display_browser_enabled="\$\(python3 [^\n]+ browser-enabled\)"; then\n'
    r'        if \[ "\$lunch_display_browser_enabled" = "true" \]; then\n'
    r'            exec startx [^\n]+ -- -nocursor\n'
    r'        fi\n'
    r'    else\n'
    r'        false\n'
    r'    fi\n'
    r'fi\n'
    r'# end lunch-display kiosk(?:\n|$)',
    re.MULTILINE,
)


def load_config():
    path = APP_DIR / "config.json"
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("must contain a JSON object")
        validate_frontend_browser_enabled(data.get("frontend_browser_enabled", True))
        validate_vnc_settings(*vnc_settings(data))
        return data
    except (OSError, ValueError) as exc:
        raise ValueError("cannot load %s: %s" % (path, exc)) from exc


def vnc_settings(data):
    return (
        data.get("vnc_enabled", True),
        data.get("vnc_port", DEFAULT_VNC_PORT),
        data.get("vnc_password", ""),
    )


def browser_enabled():
    return load_config().get("frontend_browser_enabled", True)


def vnc_enabled(data):
    """VNC shares the local kiosk display, so it needs the local browser."""
    return data.get("frontend_browser_enabled", True) and vnc_settings(data)[0]


def vnc_prepare(data, password_file):
    """Write the VNC password file and return the port, or "disabled"."""
    if not vnc_enabled(data):
        return "disabled"
    _, port, password = vnc_settings(data)
    if not password:
        raise ValueError("set vnc_password in %s to start the VNC server"
                         % (APP_DIR / "config.json"))
    path = Path(password_file)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(str(path), flags, 0o600), "w", encoding="ascii") as handle:
        handle.write(password + "\n")
    return str(port)


def profile_block():
    helper = shlex.quote(str(APP_DIR / "deploy" / "kiosk_config.py"))
    kiosk = shlex.quote(str(APP_DIR / "deploy" / "kiosk.sh"))
    return (
        MARKER + "\n"
        'if [ -z "${DISPLAY:-}" ] && [ "$(tty)" = "/dev/tty1" ]; then\n'
        '    if lunch_display_browser_enabled="$(python3 ' + helper + ' browser-enabled)"; then\n'
        '        if [ "$lunch_display_browser_enabled" = "true" ]; then\n'
        "            exec startx " + kiosk + " -- -nocursor\n"
        "        fi\n"
        "    else\n"
        "        false\n"
        "    fi\n"
        "fi\n"
        + END_MARKER + "\n"
    )


def install_profile(path, enabled):
    path = Path(path)
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    block = profile_block()
    updated, count = MANAGED_BLOCK.subn(lambda match: block, original)
    updated, legacy_count = LEGACY_BLOCK.subn(lambda match: block, updated)
    if not count and not legacy_count:
        if not enabled:
            return
        updated += ("" if not updated or updated.endswith("\n") else "\n") + block
    if updated != original:
        path.write_text(updated, encoding="utf-8")


def main():
    try:
        data = load_config()
        enabled = data.get("frontend_browser_enabled", True)
        if sys.argv[1:] == ["browser-enabled"]:
            print("true" if enabled else "false")
        elif sys.argv[1:] == ["vnc-enabled"]:
            vnc = vnc_enabled(data)
            if vnc and not vnc_settings(data)[2]:
                print("lunch-display kiosk: warning: vnc_password is empty; the VNC "
                      "server starts only after it is set", file=sys.stderr)
            print("true" if vnc else "false")
        elif len(sys.argv) == 3 and sys.argv[1] == "vnc-prepare":
            print(vnc_prepare(data, sys.argv[2]))
        elif len(sys.argv) == 3 and sys.argv[1] == "install-profile":
            install_profile(sys.argv[2], enabled)
        else:
            raise ValueError(
                "usage: kiosk_config.py browser-enabled | vnc-enabled | "
                "vnc-prepare PASSWORD_FILE | install-profile PATH"
            )
    except (OSError, ValueError) as exc:
        print("lunch-display kiosk: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
