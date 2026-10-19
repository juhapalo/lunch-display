import json
import struct
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from lunch_display.config import Config
from lunch_display.tabs import DevTools, DevToolsError, TabRotator, _read_message


class FakeDevTools:
    """In-memory stand-in for the Chromium DevTools endpoints."""

    def __init__(self):
        self.pages_by_id = {"initial": "http://localhost:8080/dashboard"}
        self.counter = 0
        self.log = []
        self.active = None
        self.unresponsive = set()
        self.available = True

    def _check(self):
        if not self.available:
            raise DevToolsError("connection refused")

    def pages(self):
        self._check()
        return list(self.pages_by_id)

    def open(self, url):
        self._check()
        self.counter += 1
        target_id = "tab%d" % self.counter
        self.pages_by_id[target_id] = url
        self.active = target_id
        self.log.append(("open", url))
        return target_id

    def activate(self, target_id):
        self._check()
        self.active = target_id
        self.log.append(("activate", self.pages_by_id[target_id]))

    def close(self, target_id):
        self._check()
        self.log.append(("close", self.pages_by_id.pop(target_id)))

    def call(self, target_id, method, params=None):
        self._check()
        if target_id in self.unresponsive or target_id not in self.pages_by_id:
            raise DevToolsError("timed out")
        self.log.append((method, self.pages_by_id[target_id]))
        return {}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class TabRotatorTest(unittest.TestCase):
    def setUp(self):
        self.config = Config(None)
        self.config.set_rotation([
            {"url": "dashboard", "duration": 60},
            {"url": "https://example.com/a", "duration": 20, "refresh": 300},
            {"url": "https://example.com/off", "duration": 20, "enabled": False},
        ])
        self.devtools = FakeDevTools()
        self.clock = Clock()
        self.rotator = TabRotator(self.config, "http://localhost:8080/",
                                  devtools=self.devtools, clock=self.clock)

    def opened(self):
        return [url for action, url in self.devtools.log if action == "open"]

    def test_tabs_are_opened_once_and_only_activated(self):
        self.assertEqual(self.rotator.step(), 60)
        self.assertEqual(self.opened(), ["http://localhost:8080/dashboard",
                                         "https://example.com/a"])
        # The browser's own start tab is closed once ours exist.
        self.assertNotIn("initial", self.devtools.pages_by_id)
        self.assertEqual(self.devtools.pages_by_id[self.devtools.active],
                         "http://localhost:8080/dashboard")
        self.devtools.log.clear()
        for expected in ("https://example.com/a", "http://localhost:8080/dashboard",
                         "https://example.com/a"):
            self.rotator.step()
            self.assertEqual(self.devtools.pages_by_id[self.devtools.active], expected)
        self.assertEqual(self.opened(), [])
        self.assertNotIn("Page.reload", [action for action, _ in self.devtools.log])
        self.assertEqual(len(self.devtools.pages_by_id), 2)

    def test_closed_tab_is_reopened(self):
        self.rotator.step()
        tab = self.rotator.tabs["https://example.com/a"]["id"]
        del self.devtools.pages_by_id[tab]
        self.devtools.log.clear()
        self.rotator.step()
        self.assertEqual(self.opened(), ["https://example.com/a"])
        self.assertEqual(self.devtools.pages_by_id[self.devtools.active],
                         "https://example.com/a")

    def test_unresponsive_tab_is_replaced(self):
        self.rotator.step()
        tab = self.rotator.tabs["https://example.com/a"]["id"]
        self.devtools.unresponsive.add(tab)
        self.rotator.step()  # First failure: may only be busy.
        self.assertIn(tab, self.devtools.pages_by_id)
        self.rotator.step()
        self.devtools.log.clear()
        self.rotator.step()  # Second failure: replaced.
        self.assertNotIn(tab, self.devtools.pages_by_id)
        self.assertEqual(self.opened(), ["https://example.com/a"])
        self.assertEqual(self.devtools.pages_by_id[self.devtools.active],
                         "https://example.com/a")

    def test_rotation_changes_open_and_close_tabs(self):
        self.rotator.step()
        self.config.set_rotation([
            {"url": "https://example.com/b", "duration": 10},
            {"url": "dashboard", "duration": 30},
        ])
        self.devtools.log.clear()
        self.rotator.step()
        self.assertEqual(self.opened(), ["https://example.com/b"])
        self.assertIn(("close", "https://example.com/a"), self.devtools.log)
        self.assertEqual(sorted(self.devtools.pages_by_id.values()),
                         ["http://localhost:8080/dashboard", "https://example.com/b"])

    def test_periodic_refresh_reloads_hidden_tabs_only(self):
        self.rotator.step()  # dashboard visible
        self.clock.now += 299
        self.rotator.refresh_due()
        self.assertNotIn("Page.reload", [action for action, _ in self.devtools.log])
        self.rotator.step()  # example.com/a visible
        self.clock.now += 10
        self.rotator.refresh_due()
        self.assertNotIn("Page.reload", [action for action, _ in self.devtools.log])
        self.rotator.step()  # dashboard visible again, /a hidden and due
        self.rotator.refresh_due()
        self.rotator.refresh_due()
        reloads = [url for action, url in self.devtools.log if action == "Page.reload"]
        self.assertEqual(reloads, ["https://example.com/a"])

    def test_single_page_is_refreshed_while_visible(self):
        self.config.set_rotation([{"url": "https://example.com/a", "duration": 30,
                                   "refresh": 60}])
        self.rotator.step()
        self.clock.now += 60
        self.rotator.refresh_due()
        self.assertIn(("Page.reload", "https://example.com/a"), self.devtools.log)

    def test_unavailable_devtools_raises_and_recovers(self):
        self.devtools.available = False
        with self.assertRaises(DevToolsError):
            self.rotator.step()
        self.assertEqual(self.rotator.position, -1)
        self.devtools.available = True
        self.rotator.step()
        self.assertEqual(self.devtools.pages_by_id[self.devtools.active],
                         "http://localhost:8080/dashboard")

    def test_empty_rotation_shows_dashboard(self):
        self.config.set_rotation([{"url": "https://example.com/a", "duration": 30,
                                   "enabled": False}])
        self.assertEqual(self.rotator.step(), 60)
        self.assertEqual(self.opened(), ["http://localhost:8080/dashboard"])


def _server_frame(payload):
    data = payload.encode("utf-8")
    if len(data) < 126:
        return bytes([0x81, len(data)]) + data
    return bytes([0x81, 126]) + struct.pack("!H", len(data)) + data


class DevToolsHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _reply(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self):
        self.server.requests.append(("PUT", self.path))
        if self.path.startswith("/json/new?"):
            return self._reply({"id": "NEW", "type": "page",
                                "url": unquote(self.path[len("/json/new?"):])})
        self.send_error(404)

    def do_GET(self):
        self.server.requests.append(("GET", self.path))
        if self.path == "/json/list":
            return self._reply([
                {"id": "A", "type": "page", "url": "https://example.com/"},
                {"id": "W", "type": "service_worker", "url": "https://example.com/sw.js"},
            ])
        if self.path.startswith(("/json/activate/", "/json/close/")):
            return self._reply("Target activated")
        if self.path.startswith("/devtools/page/"):
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.end_headers()
            self.wfile.flush()
            request = json.loads(_read_message(self.rfile))
            self.server.messages.append(request)
            self.wfile.write(_server_frame(json.dumps({"method": "Page.someEvent"})))
            if request["method"] == "Fail.me":
                reply = {"id": request["id"], "error": {"message": "nope"}}
            else:
                reply = {"id": request["id"], "result": {"echo": request["method"],
                                                         "padding": "x" * 300}}
            self.wfile.write(_server_frame(json.dumps(reply)))
            self.wfile.flush()
            self.close_connection = True
            return
        self.send_error(404)


class DevToolsClientTest(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), DevToolsHandler)
        self.server.daemon_threads = True
        self.server.requests = []
        self.server.messages = []
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.devtools = DevTools(port=self.server.server_address[1], timeout=5)

    def test_http_endpoints(self):
        self.assertEqual(self.devtools.pages(), ["A"])
        self.assertEqual(self.devtools.open("https://example.com/x?a=1&b=2#c"), "NEW")
        self.devtools.activate("A")
        self.devtools.close("A")
        self.assertEqual(self.server.requests, [
            ("GET", "/json/list"),
            ("PUT", "/json/new?https%3A%2F%2Fexample.com%2Fx%3Fa%3D1%26b%3D2%23c"),
            ("GET", "/json/activate/A"),
            ("GET", "/json/close/A"),
        ])

    def test_websocket_call(self):
        result = self.devtools.call("A", "Page.reload", {"ignoreCache": False})
        self.assertEqual(result["echo"], "Page.reload")
        self.assertEqual(self.server.messages[0]["params"], {"ignoreCache": False})
        with self.assertRaisesRegex(DevToolsError, "nope"):
            self.devtools.call("A", "Fail.me")

    def test_unavailable(self):
        self.server.shutdown()
        self.server.server_close()
        with self.assertRaises(DevToolsError):
            self.devtools.pages()
        with self.assertRaises(DevToolsError):
            self.devtools.call("A", "Runtime.evaluate")


if __name__ == "__main__":
    unittest.main()
