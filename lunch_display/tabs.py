"""Shows the rotation pages as persistent Chromium tabs.

Every enabled page is opened once in its own tab of the kiosk Chromium. A page
change only activates another tab through the Chrome DevTools Protocol HTTP
endpoints (``/json/list``, ``/json/new``, ``/json/activate/<id>``), so the pages
are not reloaded at every page change. Pages with a ``refresh`` interval are
reloaded with ``Page.reload`` (while hidden, when other tabs exist). Closed tabs
are reopened, and tabs that stop responding (crashed renderer) are replaced.
"""

import base64
import json
import logging
import os
import socket
import struct
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

from .config import DASHBOARD, MIN_DURATION

LOG = logging.getLogger("lunch_display.tabs")
DEVTOOLS_HOST = "127.0.0.1"
DEVTOOLS_PORT = 9222
DEFAULT_ROTATION = [{"url": DASHBOARD, "duration": 60, "enabled": True}]
RETRY_SECONDS = 5
TICK_SECONDS = 1
# Consecutive failed health checks before a tab is considered crashed.
MAX_FAILURES = 2
MAX_MESSAGE = 16 * 1024 * 1024


class DevToolsError(Exception):
    pass


def _encode_frame(data):
    """Masked, unfragmented WebSocket text frame (client to server)."""
    header = bytearray([0x81])
    length = len(data)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header += struct.pack("!H", length)
    else:
        header.append(0x80 | 127)
        header += struct.pack("!Q", length)
    mask = os.urandom(4)
    return bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data))


def _read_exact(reader, count):
    data = reader.read(count)
    if data is None or len(data) != count:
        raise DevToolsError("DevTools connection closed")
    return data


def _read_message(reader):
    """Read one complete WebSocket text message."""
    payload = b""
    while True:
        first, second = _read_exact(reader, 2)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", _read_exact(reader, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", _read_exact(reader, 8))[0]
        if len(payload) + length > MAX_MESSAGE:
            raise DevToolsError("DevTools message too large")
        mask = _read_exact(reader, 4) if second & 0x80 else None
        data = _read_exact(reader, length)
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        if opcode == 0x8:
            raise DevToolsError("DevTools connection closed")
        if opcode in (0x9, 0xA):
            continue
        payload += data
        if first & 0x80:
            return payload.decode("utf-8")


class DevTools:
    """Minimal Chrome DevTools Protocol client using only the standard library."""

    def __init__(self, host=DEVTOOLS_HOST, port=DEVTOOLS_PORT, timeout=15):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._next_id = 0

    def _http(self, path, method="GET"):
        url = "http://%s:%d%s" % (self.host, self.port, path)
        try:
            with urlopen(Request(url, method=method), timeout=self.timeout) as response:
                return response.read().decode("utf-8")
        except (OSError, ValueError) as exc:
            raise DevToolsError("%s %s: %s" % (method, path, exc)) from exc

    def _json(self, path, method="GET"):
        try:
            return json.loads(self._http(path, method))
        except ValueError as exc:
            raise DevToolsError("invalid DevTools response: %s" % exc) from exc

    def pages(self):
        """Ids of the open page targets (tabs)."""
        targets = self._json("/json/list")
        if not isinstance(targets, list):
            raise DevToolsError("invalid DevTools target list")
        return [target["id"] for target in targets
                if isinstance(target, dict) and target.get("type") == "page"
                and isinstance(target.get("id"), str)]

    def open(self, url):
        # Chromium 111+ requires PUT; older versions accept any method.
        target = self._json("/json/new?" + quote(url, safe=""), method="PUT")
        if not isinstance(target, dict) or not isinstance(target.get("id"), str):
            raise DevToolsError("invalid DevTools response for a new tab")
        return target["id"]

    def activate(self, target_id):
        self._http("/json/activate/" + quote(target_id, safe=""))

    def close(self, target_id):
        self._http("/json/close/" + quote(target_id, safe=""))

    def call(self, target_id, method, params=None):
        """Send one protocol command to a tab and return its result."""
        self._next_id += 1
        message = {"id": self._next_id, "method": method, "params": params or {}}
        path = "/devtools/page/" + quote(target_id, safe="")
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                key = base64.b64encode(os.urandom(16)).decode("ascii")
                sock.sendall((
                    "GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\n"
                    "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
                    "Sec-WebSocket-Version: 13\r\n\r\n" % (path, self.host, self.port, key)
                ).encode("ascii"))
                reader = sock.makefile("rb")
                status = reader.readline(1024).split()
                if len(status) < 2 or status[1] != b"101":
                    raise DevToolsError("DevTools refused the connection to %s" % target_id)
                while reader.readline(8192) not in (b"\r\n", b"\n", b""):
                    pass
                sock.sendall(_encode_frame(json.dumps(message).encode("utf-8")))
                while True:
                    reply = json.loads(_read_message(reader))
                    if isinstance(reply, dict) and reply.get("id") == message["id"]:
                        break
        except (OSError, ValueError) as exc:
            raise DevToolsError("%s on %s: %s" % (method, target_id, exc)) from exc
        if "error" in reply:
            raise DevToolsError("%s on %s: %s" % (method, target_id, reply["error"]))
        return reply.get("result", {})


class TabRotator:
    """Keeps one tab per configured page and activates them in turn."""

    def __init__(self, config, base_url, devtools=None, clock=time.monotonic,
                 sleep=time.sleep):
        self.config = config
        self.base_url = base_url.rstrip("/")
        self.devtools = devtools or DevTools()
        self.clock = clock
        self.sleep = sleep
        self.tabs = {}  # resolved url -> {"id", "loaded", "failures"}
        self.refresh = {}  # resolved url -> refresh interval in seconds
        self.position = -1
        self.current = None

    def resolve(self, url):
        return self.base_url + "/dashboard" if url == DASHBOARD else url

    def rotation(self):
        items = [item for item in self.config.get("rotation") if item.get("enabled", True)]
        return items or DEFAULT_ROTATION

    def _open(self, url):
        self.tabs[url] = {"id": self.devtools.open(url), "loaded": self.clock(), "failures": 0}

    def _close(self, target_id):
        try:
            self.devtools.close(target_id)
        except DevToolsError as exc:
            LOG.debug("Closing tab %s failed: %s", target_id, exc)

    def sync(self, items):
        """Open a tab for every page, reopen closed tabs and close the rest."""
        wanted = []
        refresh = {}
        for item in items:
            url = self.resolve(item["url"])
            if url not in wanted:
                wanted.append(url)
            interval = item.get("refresh") or 0
            if interval and (url not in refresh or interval < refresh[url]):
                refresh[url] = interval
        self.refresh = refresh
        live = set(self.devtools.pages())
        for url, tab in list(self.tabs.items()):
            if url not in wanted or tab["id"] not in live:
                if tab["id"] in live:
                    live.discard(tab["id"])
                    self._close(tab["id"])
                else:
                    LOG.info("Tab for %s was closed, reopening", url)
                del self.tabs[url]
        for url in wanted:
            if url not in self.tabs:
                self._open(url)
        # Our tabs exist now, so closing the others never closes the last tab
        # (which would end the browser).
        managed = {tab["id"] for tab in self.tabs.values()}
        for target_id in live - managed:
            self._close(target_id)

    def ensure_alive(self, url):
        """Replace the tab if it no longer answers (crashed renderer)."""
        tab = self.tabs[url]
        try:
            self.devtools.call(tab["id"], "Runtime.evaluate", {"expression": "1"})
        except DevToolsError as exc:
            tab["failures"] += 1
            LOG.warning("Tab for %s is not responding (%d): %s", url, tab["failures"], exc)
            if tab["failures"] >= MAX_FAILURES:
                old = tab["id"]
                self._open(url)
                self._close(old)
        else:
            tab["failures"] = 0

    def step(self):
        """Show the next page; returns how many seconds it stays visible."""
        items = self.rotation()
        position = (self.position + 1) % len(items)
        item = items[position]
        url = self.resolve(item["url"])
        self.sync(items)
        self.ensure_alive(url)
        self.devtools.activate(self.tabs[url]["id"])
        self.position = position
        self.current = url
        return max(MIN_DURATION, int(item.get("duration") or 60))

    def refresh_due(self):
        """Reload pages whose refresh interval has passed."""
        now = self.clock()
        for url, tab in list(self.tabs.items()):
            interval = self.refresh.get(url)
            if not interval or now - tab["loaded"] < interval:
                continue
            # Reload hidden tabs only, so nobody sees the page reloading.
            if url == self.current and len(self.tabs) > 1:
                continue
            tab["loaded"] = now
            try:
                self.devtools.call(tab["id"], "Page.reload")
            except DevToolsError as exc:
                LOG.warning("Reloading %s failed: %s", url, exc)

    def run_forever(self):
        next_switch = 0.0
        offline = False
        while True:
            try:
                if self.clock() >= next_switch:
                    next_switch = self.clock() + self.step()
                self.refresh_due()
            except DevToolsError as exc:
                if not offline:
                    LOG.info("Chromium DevTools not available, retrying: %s", exc)
                offline = True
                next_switch = self.clock() + RETRY_SECONDS
            except Exception:
                LOG.exception("Tab rotation failed")
                next_switch = self.clock() + RETRY_SECONDS
            else:
                if offline:
                    LOG.info("Connected to Chromium DevTools")
                offline = False
            self.sleep(TICK_SECONDS)
