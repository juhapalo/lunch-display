#!/usr/bin/env python3
"""Check kiosk configuration and maintain its managed login-profile block."""

import json
from pathlib import Path
import re
import shlex
import sys

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from lunch_display.config import validate_frontend_browser_enabled


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


def browser_enabled():
    path = APP_DIR / "config.json"
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("must contain a JSON object")
        return validate_frontend_browser_enabled(
            data.get("frontend_browser_enabled", True)
        )
    except (OSError, ValueError) as exc:
        raise ValueError("cannot load %s: %s" % (path, exc)) from exc


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
        enabled = browser_enabled()
        if sys.argv[1:] == ["browser-enabled"]:
            print("true" if enabled else "false")
        elif len(sys.argv) == 3 and sys.argv[1] == "install-profile":
            install_profile(sys.argv[2], enabled)
        else:
            raise ValueError("usage: kiosk_config.py browser-enabled | install-profile PATH")
    except (OSError, ValueError) as exc:
        print("lunch-display kiosk: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
