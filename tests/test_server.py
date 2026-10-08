import base64
import http.client
import json
import os
import tempfile
import threading
import unittest

from lunch_display.config import Config, validate_rotation
from lunch_display.server import App, DataStore

TEST_PASSWORD = "unit" + "-test-" + "pw"


class ValidateRotationTest(unittest.TestCase):
    def test_valid(self):
        result = validate_rotation([
            {"url": "dashboard", "duration": 60},
            {"url": " https://example.com/x ", "duration": "30", "enabled": False},
        ])
        self.assertEqual(result, [
            {"url": "dashboard", "duration": 60, "enabled": True},
            {"url": "https://example.com/x", "duration": 30, "enabled": False},
        ])

    def test_invalid(self):
        bad = [
            "nope",
            [{"url": "javascript:alert(1)", "duration": 30}],
            [{"url": "file:///etc/passwd", "duration": 30}],
            [{"url": "https://example.com", "duration": 1}],
            [{"url": "https://example.com", "duration": "abc"}],
            [{"url": "https://example.com", "duration": True}],
            ["https://example.com"],
        ]
        for rotation in bad:
            with self.assertRaises(ValueError, msg=repr(rotation)):
                validate_rotation(rotation)


class ConfigTest(unittest.TestCase):
    def test_defaults_and_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with open(path, "w") as handle:
                json.dump({"listen_port": 9000, "location": {"name": "Espoo"}}, handle)
            config = Config(path)
            self.assertEqual(config.get("listen_port"), 9000)
            self.assertEqual(config.get("location")["name"], "Espoo")
            self.assertEqual(config.get("location")["timezone"], "Europe/Helsinki")
            self.assertEqual(len(config.get("restaurants")), 3)

            config.set_rotation([{"url": "https://example.com", "duration": 10}])
            reloaded = Config(path)
            self.assertEqual(reloaded.get("rotation")[0]["url"], "https://example.com")
            self.assertEqual(reloaded.get("listen_port"), 9000)


class DataStoreTest(unittest.TestCase):
    def test_refresh_and_errors(self):
        config = Config(None)

        def fetch_weather(location):
            raise OSError("offline")

        def fetch_menu(restaurant, day):
            return {"name": restaurant["name"], "items": ["Keitto"], "url": "", "error": None}

        store = DataStore(config, fetch_weather, fetch_menu)
        self.assertTrue(store.refresh(now=1000))
        snapshot = store.snapshot()
        self.assertEqual(snapshot["weather_error"], "Säätietoja ei saatu haettua")
        self.assertEqual([m["name"] for m in snapshot["menus"]],
                         ["Flying Dylan", "Ravintola Factory Aviapolis", "Huili Kehä 3 Vantaa"])
        self.assertFalse(store.refresh(now=1001))  # nothing stale yet
        store.request_refresh()
        self.assertTrue(store.refresh(now=1002))


class ServerTest(unittest.TestCase):
    def start(self, password=""):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "config.json")
        with open(path, "w") as handle:
            json.dump({"admin_password": password}, handle)
        config = Config(path)
        store = DataStore(config, lambda loc: {"current": {"temperature": 5}},
                          lambda r, d: {"name": r["name"], "items": ["Ruoka"], "url": "", "error": None})
        store.refresh()
        server = App(config, store).make_server("127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def request(self, port, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    def test_pages_and_api(self):
        port = self.start()
        for path in ("/", "/dashboard", "/admin", "/static/rotator.js", "/static/dashboard.css"):
            status, _ = self.request(port, "GET", path)
            self.assertEqual(status, 200, path)
        self.assertEqual(self.request(port, "GET", "/static/../server.py")[0], 404)
        self.assertEqual(self.request(port, "GET", "/static/missing.js")[0], 404)

        status, body = self.request(port, "GET", "/api/data")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(data["weather"]["current"]["temperature"], 5)
        self.assertEqual(len(data["menus"]), 3)

        status, body = self.request(port, "GET", "/api/rotation")
        self.assertEqual(json.loads(body)["rotation"][0]["url"], "dashboard")

    def test_update_rotation_locally(self):
        port = self.start()
        new = {"rotation": [{"url": "dashboard", "duration": 45},
                            {"url": "https://example.com", "duration": 20}]}
        status, body = self.request(port, "POST", "/api/rotation", json.dumps(new),
                                    {"Content-Type": "application/json"})
        self.assertEqual(status, 200, body)
        status, body = self.request(port, "GET", "/api/rotation")
        self.assertEqual(json.loads(body)["rotation"][1]["duration"], 20)

        status, _ = self.request(port, "POST", "/api/rotation", json.dumps({"rotation": [{"url": "ftp://x"}]}),
                                 {"Content-Type": "application/json"})
        self.assertEqual(status, 400)
        status, _ = self.request(port, "POST", "/api/rotation", json.dumps(new),
                                 {"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        status, _ = self.request(port, "POST", "/api/rotation", json.dumps(new),
                                 {"Content-Type": "application/json", "Origin": "http://evil.example"})
        self.assertEqual(status, 403)

    def test_password_protection(self):
        port = self.start(TEST_PASSWORD)
        self.assertEqual(self.request(port, "GET", "/admin")[0], 401)
        bad = "Basic " + base64.b64encode(b"admin:wrong").decode()
        self.assertEqual(self.request(port, "GET", "/admin", headers={"Authorization": bad})[0], 401)
        good = "Basic " + base64.b64encode(b"admin:" + TEST_PASSWORD.encode()).decode()
        self.assertEqual(self.request(port, "GET", "/admin", headers={"Authorization": good})[0], 200)
        status, _ = self.request(port, "POST", "/api/refresh", "{}",
                                 {"Content-Type": "application/json", "Authorization": good})
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
