"""Small HTTP helper based on the standard library only."""

import re
import urllib.request

USER_AGENT = "Mozilla/5.0 (X11; Linux armv6l) lunch-display/1.0"
MAX_BYTES = 5 * 1024 * 1024


def fetch_text(url, timeout=20):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "fi,en;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_BYTES)
        charset = response.headers.get_content_charset()
    if not charset:
        match = re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', raw[:4096], re.I)
        charset = match.group(1).decode("ascii") if match else "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")
