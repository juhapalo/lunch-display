"""Weather from the free Open-Meteo API (no API key needed)."""

import json
from urllib.parse import urlencode

from .fetch import fetch_text

API_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes -> (Finnish description, icon)
WMO_CODES = {
    0: ("Selkeää", "☀️"),
    1: ("Enimmäkseen selkeää", "🌤️"),
    2: ("Puolipilvistä", "⛅"),
    3: ("Pilvistä", "☁️"),
    45: ("Sumua", "🌫️"),
    48: ("Kuurasumua", "🌫️"),
    51: ("Heikkoa tihkua", "🌦️"),
    53: ("Tihkusadetta", "🌦️"),
    55: ("Voimakasta tihkua", "🌧️"),
    56: ("Jäätävää tihkua", "🌧️"),
    57: ("Voimakasta jäätävää tihkua", "🌧️"),
    61: ("Heikkoa sadetta", "🌦️"),
    63: ("Sadetta", "🌧️"),
    65: ("Voimakasta sadetta", "🌧️"),
    66: ("Jäätävää sadetta", "🌧️"),
    67: ("Voimakasta jäätävää sadetta", "🌧️"),
    71: ("Heikkoa lumisadetta", "🌨️"),
    73: ("Lumisadetta", "🌨️"),
    75: ("Voimakasta lumisadetta", "❄️"),
    77: ("Lumijyväsiä", "🌨️"),
    80: ("Heikkoja sadekuuroja", "🌦️"),
    81: ("Sadekuuroja", "🌧️"),
    82: ("Voimakkaita sadekuuroja", "⛈️"),
    85: ("Lumikuuroja", "🌨️"),
    86: ("Voimakkaita lumikuuroja", "❄️"),
    95: ("Ukkosta", "⛈️"),
    96: ("Ukkosta ja raekuuroja", "⛈️"),
    99: ("Voimakasta ukkosta ja rakeita", "⛈️"),
}


def describe(code):
    try:
        code = int(code)
    except (TypeError, ValueError):
        return ("", "")
    return WMO_CODES.get(code, ("", ""))


def build_url(latitude, longitude, timezone):
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "hourly": "temperature_2m,weather_code,precipitation_probability",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset",
        "wind_speed_unit": "ms",
        "forecast_days": 1,
        # Override the midnight cutoff: current hour plus 24 upcoming hours.
        "forecast_hours": 25,
    }
    return API_URL + "?" + urlencode(params)


def _round(value):
    return None if value is None else int(round(value))


def parse_weather(data, hours=12):
    """Return up to hours upcoming even-hour forecasts, plus current/daily data."""
    current = data.get("current", {})
    description, icon = describe(current.get("weather_code"))
    result = {
        "current": {
            "temperature": _round(current.get("temperature_2m")),
            "feels_like": _round(current.get("apparent_temperature")),
            "wind": current.get("wind_speed_10m"),
            "description": description,
            "icon": icon,
            "time": current.get("time"),
        },
        "hours": [],
        "today": None,
    }

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    codes = hourly.get("weather_code", [])
    rain = hourly.get("precipitation_probability", [])
    now = current.get("time") or ""
    # Open-Meteo returns local ISO times ("2026-10-08T10:15"); compare by hour.
    now_hour = now[:13]
    for index, stamp in enumerate(times):
        if stamp[:13] <= now_hour:
            continue
        if int(stamp[11:13]) % 2:
            continue
        desc, hour_icon = describe(codes[index] if index < len(codes) else None)
        result["hours"].append(
            {
                "time": stamp[11:16],
                "temperature": _round(temps[index]) if index < len(temps) else None,
                "precipitation_probability": rain[index] if index < len(rain) else None,
                "description": desc,
                "icon": hour_icon,
            }
        )
        if len(result["hours"]) >= hours:
            break

    daily = data.get("daily", {})
    if daily.get("time"):
        desc, day_icon = describe((daily.get("weather_code") or [None])[0])
        result["today"] = {
            "max": _round((daily.get("temperature_2m_max") or [None])[0]),
            "min": _round((daily.get("temperature_2m_min") or [None])[0]),
            "sunrise": ((daily.get("sunrise") or [""])[0] or "")[11:16],
            "sunset": ((daily.get("sunset") or [""])[0] or "")[11:16],
            "description": desc,
            "icon": day_icon,
        }
    return result


def get_weather(location):
    url = build_url(location["latitude"], location["longitude"], location["timezone"])
    data = json.loads(fetch_text(url))
    weather = parse_weather(data)
    weather["location"] = location.get("name", "")
    return weather
