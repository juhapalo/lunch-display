import base64
import datetime
import http.client
import json
import os
import tempfile
import threading
import unittest

from lunch_display.config import Config, validate_rotation
from lunch_display.server import App, DataStore, local_time, menu_target_date

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
    def test_cutoff_refreshes_even_when_not_stale(self):
        fetched = []
        store = DataStore(Config(None), lambda loc: {},
                          lambda r, d: fetched.append(d) or {"items": []})
        before = datetime.datetime(2026, 10, 8, 10, 59, tzinfo=datetime.timezone.utc).timestamp()
        store.refresh(before)
        self.assertEqual(store.snapshot()["menus_date"], "2026-10-08")
        store.refresh(before + 60)
        self.assertEqual(store.snapshot()["menus_date"], "2026-10-09")
        self.assertEqual(fetched, [datetime.date(2026, 10, 8)] * 3 +
                         [datetime.date(2026, 10, 9)] * 3)
        self.assertFalse(store.refresh(before + 61))

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


class MenuTargetDateTest(unittest.TestCase):
    def test_workdays_and_rollovers(self):
        cases = [
            ("2026-10-08T13:59", "2026-10-08"),
            ("2026-10-08T14:00", "2026-10-09"),
            ("2026-10-09T14:00", "2026-10-12"),
            ("2026-10-10T09:00", "2026-10-12"),
            ("2026-10-11T15:00", "2026-10-12"),
            ("2026-10-30T14:00", "2026-11-02"),
            ("2027-12-31T14:00", "2028-01-03"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                local = datetime.datetime.fromisoformat(value).replace(
                    tzinfo=datetime.timezone(datetime.timedelta(hours=3)))
                self.assertEqual(menu_target_date(local).isoformat(), expected)

    def test_helsinki_dst_independent_of_host_timezone(self):
        cases = [("2026-03-27T11:59", 13, "2026-03-27"),
                 ("2026-03-27T12:00", 14, "2026-03-30"),
                 ("2026-03-30T11:00", 14, "2026-03-31"),
                 ("2026-10-23T11:00", 14, "2026-10-26"),
                 ("2026-10-26T11:59", 13, "2026-10-26"),
                 ("2026-10-26T12:00", 14, "2026-10-27")]
        for value, hour, expected in cases:
            utc = datetime.datetime.fromisoformat(value).replace(tzinfo=datetime.timezone.utc)
            local = local_time("Europe/Helsinki", utc.timestamp())
            self.assertEqual(local.hour, hour)
            self.assertEqual(menu_target_date(local).isoformat(), expected)
        for value, offset in [("2026-03-29T00:59", 2), ("2026-03-29T01:00", 3),
                              ("2026-10-25T00:59", 3), ("2026-10-25T01:00", 2)]:
            utc = datetime.datetime.fromisoformat(value).replace(tzinfo=datetime.timezone.utc)
            local = local_time("Europe/Helsinki", utc.timestamp())
            self.assertEqual(local.utcoffset(), datetime.timedelta(hours=offset))
        utc = datetime.datetime(2026, 10, 8, 11, tzinfo=datetime.timezone.utc).timestamp()
        self.assertEqual(menu_target_date(local_time("UTC", utc)), datetime.date(2026, 10, 8))
        self.assertEqual(menu_target_date(local_time("Europe/Helsinki", utc)),
                         datetime.date(2026, 10, 9))

    def test_invalid_timezone_is_not_silently_local(self):
        with self.assertRaises(KeyError):
            local_time("Invalid/Timezone", 0)


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
        self.assertEqual(data["date"], data["local_time"][:10])
        self.assertIsNotNone(data["menus_date"])

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
