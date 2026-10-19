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
MIN_REFRESH = 30
DEFAULT_VNC_PORT = 5900

DEFAULT_CONFIG = {
    "listen_host": "0.0.0.0",
    "listen_port": 8080,
    "frontend_browser_enabled": True,
    # x11vnc server sharing the kiosk display. It only starts once
    # vnc_password is set.
    "vnc_enabled": True,
    "vnc_port": DEFAULT_VNC_PORT,
    "vnc_password": "",
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
    # weather + lunch view, anything else is an http(s) URL. An optional
    # "refresh" (seconds, 0 = never) periodically reloads the page.
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


def validate_frontend_browser_enabled(value):
    """Accept only a JSON boolean, not truthy strings or numbers."""
    if not isinstance(value, bool):
        raise ValueError("frontend_browser_enabled must be a JSON boolean")
    return value


def validate_vnc_settings(enabled, port, password):
    """Validate the VNC server settings; returns them unchanged."""
    if not isinstance(enabled, bool):
        raise ValueError("vnc_enabled must be a JSON boolean")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("vnc_port must be an integer between 1 and 65535")
    # x11vnc reads the password from the first line of a password file where
    # "#" comments out a line and "__" starts special tokens.
    if (not isinstance(password, str)
            or any(not "!" <= char <= "~" for char in password)
            or password.startswith("#") or "__" in password):
        raise ValueError(
            "vnc_password must be printable ASCII without spaces, must not "
            "start with '#' and must not contain '__'"
        )
    return enabled, port, password


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
        refresh = item.get("refresh", 0)
        if refresh is None or refresh == "":
            refresh = 0
        if isinstance(refresh, bool):
            raise ValueError("item %d: refresh must be a number" % (index + 1))
        try:
            refresh = int(refresh)
        except (TypeError, ValueError):
            raise ValueError("item %d: refresh must be a number" % (index + 1))
        if refresh != 0 and not MIN_REFRESH <= refresh <= MAX_DURATION:
            raise ValueError(
                "item %d: refresh must be 0 (never) or between %d and %d seconds"
                % (index + 1, MIN_REFRESH, MAX_DURATION)
            )
        enabled = item.get("enabled", True)
        entry = {"url": url, "duration": duration, "enabled": bool(enabled)}
        if refresh:
            entry["refresh"] = refresh
        cleaned.append(entry)
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
        self._data["frontend_browser_enabled"] = validate_frontend_browser_enabled(
            self._data["frontend_browser_enabled"]
        )
        validate_vnc_settings(
            self._data["vnc_enabled"], self._data["vnc_port"], self._data["vnc_password"]
        )
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
