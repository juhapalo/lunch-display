"""Configuration loading, validation and saving."""

import copy
import json
import os
import threading
from urllib.parse import urlparse

DASHBOARD = "dashboard"
MIN_DURATION = 5
MAX_DURATION = 24 * 60 * 60
MAX_ROTATION_ITEMS = 50
MAX_URL_LENGTH = 2000

DEFAULT_CONFIG = {
    "listen_host": "0.0.0.0",
    "listen_port": 8080,
    # When empty, the admin page can only be used from the Pi itself
    # (localhost). Set a password to allow editing from other machines.
    "admin_password": "",
    "location": {
        "name": "Vantaa",
        "latitude": 60.2941,
        "longitude": 25.0410,
        "timezone": "Europe/Helsinki",
    },
    "weather_refresh_minutes": 15,
    "menu_refresh_minutes": 60,
    "restaurants": [
        {
            "name": "Flying Dylan",
            "urls": [
                "https://www.dylan.fi/flyingdylan",
                "https://www.lounaat.info/lounas/flying-dylan/vantaa",
            ],
        },
        {
            "name": "Ravintola Factory Aviapolis",
            "urls": [
                "https://ravintolafactory.com/lounasravintolat/ravintolat/factory-aviapolis/",
            ],
        },
        {
            "name": "Huili Kehä 3 Vantaa",
            "urls": [
                "https://huilipiste.fi/ravintola/huili-keha-3-vantaa/",
            ],
        },
    ],
    # Pages shown in sequential order. "dashboard" is the built-in
    # weather + lunch view, anything else is an http(s) URL.
    "rotation": [
        {"url": DASHBOARD, "duration": 60},
    ],
}


def _merge(base, override):
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def is_valid_page_url(url):
    if not isinstance(url, str) or not url or len(url) > MAX_URL_LENGTH:
        return False
    if url == DASHBOARD:
        return True
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def validate_rotation(rotation):
    """Validate and normalise a rotation list.

    Returns the cleaned list or raises ValueError.
    """
    if not isinstance(rotation, list):
        raise ValueError("rotation must be a list")
    if len(rotation) > MAX_ROTATION_ITEMS:
        raise ValueError("too many pages (max %d)" % MAX_ROTATION_ITEMS)
    cleaned = []
    for index, item in enumerate(rotation):
        if not isinstance(item, dict):
            raise ValueError("item %d must be an object" % (index + 1))
        url = item.get("url")
        if isinstance(url, str):
            url = url.strip()
        if not is_valid_page_url(url):
            raise ValueError(
                "item %d: url must be 'dashboard' or an http(s) URL" % (index + 1)
            )
        duration = item.get("duration")
        if isinstance(duration, bool):
            raise ValueError("item %d: duration must be a number" % (index + 1))
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            raise ValueError("item %d: duration must be a number" % (index + 1))
        if not MIN_DURATION <= duration <= MAX_DURATION:
            raise ValueError(
                "item %d: duration must be between %d and %d seconds"
                % (index + 1, MIN_DURATION, MAX_DURATION)
            )
        enabled = item.get("enabled", True)
        cleaned.append({"url": url, "duration": duration, "enabled": bool(enabled)})
    return cleaned


class Config:
    """Thread-safe configuration backed by a JSON file."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._data = copy.deepcopy(DEFAULT_CONFIG)
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                user = json.load(handle)
            if not isinstance(user, dict):
                raise ValueError("%s must contain a JSON object" % path)
            self._data = _merge(DEFAULT_CONFIG, user)
        self._data["rotation"] = validate_rotation(self._data.get("rotation", []))

    def get(self, key):
        with self._lock:
            return copy.deepcopy(self._data[key])

    def set_rotation(self, rotation):
        cleaned = validate_rotation(rotation)
        with self._lock:
            self._data["rotation"] = cleaned
            self._save_locked()
        return cleaned

    def _save_locked(self):
        if not self.path:
            return
        directory = os.path.dirname(os.path.abspath(self.path))
        tmp_path = os.path.join(directory, ".config.json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(self._data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp_path, self.path)
