"""HTTP server: serves the display pages, data API and admin page."""

import argparse
import base64
import datetime
import hmac
import ipaddress
import json
import logging
import os
import threading
import time
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import menus, weather
from .config import Config

LOG = logging.getLogger("lunch_display")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_BODY = 64 * 1024

PAGES = {
    "/": "index.html",
    "/dashboard": "dashboard.html",
    "/admin": "admin.html",
}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}


def local_time(timezone, now=None):
    return datetime.datetime.fromtimestamp(
        time.time() if now is None else now, ZoneInfo(timezone))


def today_in(timezone):
    return local_time(timezone).date()


def menu_target_date(local):
    day = local.date()
    if local.hour >= 14 and day.weekday() < 5:
        day += datetime.timedelta(days=1)
    while day.weekday() >= 5:
        day += datetime.timedelta(days=1)
    return day


class DataStore:
    """Keeps the latest weather and menus, refreshed in a background thread."""

    def __init__(self, config, fetch_weather=weather.get_weather, fetch_menu=menus.get_menu):
        self.config = config
        self.fetch_weather = fetch_weather
        self.fetch_menu = fetch_menu
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._weather = None
        self._weather_error = None
        self._weather_time = 0.0
        self._menus = []
        self._menus_date = None
        self._menus_time = 0.0

    def snapshot(self):
        with self._lock:
            return {
                "weather": self._weather,
                "weather_error": self._weather_error,
                "menus": self._menus,
                "menus_date": self._menus_date.isoformat() if self._menus_date else None,
                "updated": int(max(self._weather_time, self._menus_time)),
            }

    def request_refresh(self):
        with self._lock:
            self._weather_time = 0.0
            self._menus_time = 0.0
        self._wake.set()

    def refresh(self, now=None):
        """Refresh whatever is stale. Returns True if something was updated."""
        now = time.time() if now is None else now
        location = self.config.get("location")
        day = menu_target_date(local_time(location.get("timezone", "Europe/Helsinki"), now))
        updated = False

        weather_age = now - self._weather_time
        if weather_age >= self.config.get("weather_refresh_minutes") * 60:
            try:
                data, error = self.fetch_weather(location), None
            except Exception as exc:
                LOG.warning("Weather fetch failed: %s", exc)
                data, error = None, "Säätietoja ei saatu haettua"
            with self._lock:
                if data is not None:
                    self._weather = data
                self._weather_error = error
                self._weather_time = now
            updated = True

        menu_age = now - self._menus_time
        if day != self._menus_date or menu_age >= self.config.get("menu_refresh_minutes") * 60:
            results = []
            for restaurant in self.config.get("restaurants"):
                try:
                    results.append(self.fetch_menu(restaurant, day))
                except Exception as exc:
                    LOG.warning("Menu fetch failed for %s: %s", restaurant.get("name"), exc)
                    results.append({"name": restaurant.get("name", ""), "items": [],
                                    "url": "", "error": menus.unavailable_message(day)})
            with self._lock:
                self._menus = results
                self._menus_date = day
                self._menus_time = now
            updated = True
        return updated

    def run_forever(self, interval=30):
        while True:
            try:
                self.refresh()
            except Exception:
                LOG.exception("Refresh failed")
            self._wake.wait(interval)
            self._wake.clear()


class Handler(BaseHTTPRequestHandler):
    server_version = "LunchDisplay/1.0"

    @property
    def app(self):
        return self.server.app

    def log_message(self, fmt, *args):
        LOG.debug("%s - %s", self.address_string(), fmt % args)

    # --- helpers -------------------------------------------------------
    def _send(self, status, body, content_type, extra_headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, payload):
        self._send(status, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")

    def _file(self, name):
        path = self.app.static_files[name]
        with open(path, "rb") as handle:
            body = handle.read()
        content_type = CONTENT_TYPES.get(os.path.splitext(name)[1], "application/octet-stream")
        self._send(200, body, content_type)

    def _is_local(self):
        try:
            return ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            return False

    def _authorized(self):
        password = self.app.config.get("admin_password")
        if not password:
            if self._is_local():
                return True
            self._json(403, {"error": "Set admin_password in config.json to edit remotely"})
            return False
        header = self.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                decoded = base64.b64decode(header[6:]).decode("utf-8")
                supplied = decoded.split(":", 1)[1]
            except (ValueError, IndexError, UnicodeDecodeError):
                supplied = ""
            if hmac.compare_digest(supplied.encode("utf-8"), password.encode("utf-8")):
                return True
        self._send(401, "Authentication required", "text/plain; charset=utf-8",
                   {"WWW-Authenticate": 'Basic realm="lunch-display"'})
        return False

    def _same_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return urlparse(origin).netloc == self.headers.get("Host", "")

    def _is_json(self):
        content_type = self.headers.get("Content-Type", "").split(";")[0].strip()
        return content_type.lower() == "application/json"

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("invalid Content-Length")
        if length <= 0 or length > MAX_BODY:
            raise ValueError("invalid request body size")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    # --- routes --------------------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/admin" and not self._authorized():
            return
        if path in PAGES:
            return self._file(PAGES[path])
        if path.startswith("/static/"):
            name = path[len("/static/"):]
            if name in self.app.static_files:
                return self._file(name)
        if path == "/api/data":
            payload = self.app.store.snapshot()
            local = local_time(self.app.config.get("location")["timezone"])
            payload["date"] = local.date().isoformat()
            payload["local_time"] = local.replace(tzinfo=None).isoformat()
            return self._json(200, payload)
        if path == "/api/rotation":
            return self._json(200, {"rotation": self.app.config.get("rotation")})
        self._send(404, "Not found", "text/plain; charset=utf-8")

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/api/rotation", "/api/refresh"):
            return self._send(404, "Not found", "text/plain; charset=utf-8")
        if not self._same_origin():
            return self._json(403, {"error": "cross-origin request rejected"})
        if not self._is_json():
            return self._json(415, {"error": "Content-Type must be application/json"})
        if not self._authorized():
            return
        if path == "/api/refresh":
            self.app.store.request_refresh()
            return self._json(200, {"ok": True})
        try:
            body = self._read_json()
            if not isinstance(body, dict):
                raise ValueError("expected a JSON object")
            rotation = self.app.config.set_rotation(body.get("rotation"))
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        except OSError as exc:
            LOG.error("Saving config failed: %s", exc)
            return self._json(500, {"error": "could not save configuration"})
        self._json(200, {"rotation": rotation})


class App:
    def __init__(self, config, store=None):
        self.config = config
        ZoneInfo(config.get("location")["timezone"])
        self.store = store or DataStore(config)
        # Only these pre-scanned files are ever served (name -> path).
        self.static_files = {
            name: os.path.join(STATIC_DIR, name)
            for name in os.listdir(STATIC_DIR)
            if os.path.splitext(name)[1] in CONTENT_TYPES
        }

    def make_server(self, host=None, port=None):
        host = self.config.get("listen_host") if host is None else host
        port = self.config.get("listen_port") if port is None else port
        server = ThreadingHTTPServer((host, port), Handler)
        server.daemon_threads = True
        server.app = self
        return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="Raspberry Pi lunch display server")
    parser.add_argument("-c", "--config", default="config.json",
                        help="path to config.json (created/updated by the admin page)")
    parser.add_argument("--host", help="override listen_host")
    parser.add_argument("--port", type=int, help="override listen_port")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    app = App(Config(args.config))
    server = app.make_server(args.host, args.port)
    threading.Thread(target=app.store.run_forever, daemon=True).start()
    host, port = server.server_address[:2]
    LOG.info("Serving on http://%s:%s/ (admin: /admin)", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
