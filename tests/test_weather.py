import copy
import unittest
from urllib.parse import parse_qs, urlparse

from lunch_display import weather

SAMPLE = {
    "current": {
        "time": "2026-10-08T10:15",
        "temperature_2m": 7.6,
        "apparent_temperature": 4.2,
        "weather_code": 3,
        "wind_speed_10m": 4.5,
    },
    "hourly": {
        "time": ["2026-10-08T%02d:00" % h for h in range(24)],
        "temperature_2m": [float(h) for h in range(24)],
        "weather_code": [61] * 24,
        "precipitation_probability": [40] * 24,
    },
    "daily": {
        "time": ["2026-10-08", "2026-10-09"],
        "weather_code": [61, 0],
        "temperature_2m_max": [9.4, 10.0],
        "temperature_2m_min": [3.5, 2.0],
        "sunrise": ["2026-10-08T07:48", "2026-10-09T07:50"],
        "sunset": ["2026-10-08T18:31", "2026-10-09T18:28"],
    },
}


class WeatherTest(unittest.TestCase):
    def test_parse_weather(self):
        result = weather.parse_weather(SAMPLE, hours=3)
        self.assertEqual(result["current"]["temperature"], 8)
        self.assertEqual(result["current"]["feels_like"], 4)
        self.assertEqual(result["current"]["description"], "Pilvistä")
        self.assertEqual([h["time"] for h in result["hours"]], ["11:00", "12:00", "13:00"])
        self.assertEqual(result["hours"][0]["temperature"], 11)
        self.assertEqual(result["hours"][0]["precipitation_probability"], 40)
        self.assertEqual(result["today"]["max"], 9)
        self.assertEqual(result["today"]["min"], 4)
        self.assertEqual(result["today"]["sunrise"], "07:48")

    def test_parse_handles_empty_response(self):
        result = weather.parse_weather({})
        self.assertIsNone(result["current"]["temperature"])
        self.assertEqual(result["hours"], [])
        self.assertIsNone(result["today"])

    def test_default_forecast_has_24_upcoming_hours(self):
        data = copy.deepcopy(SAMPLE)
        for key, values in data["hourly"].items():
            values.extend(
                ["2026-10-09T%02d:00" % h for h in range(24)]
                if key == "time" else list(values)
            )
        for now, first, last in [
            ("2026-10-08T10:15", "11:00", "10:00"),
            ("2026-10-08T23:45", "00:00", "23:00"),
        ]:
            with self.subTest(now=now):
                data["current"]["time"] = now
                result = weather.parse_weather(data)
                self.assertEqual(len(result["hours"]), 24)
                self.assertEqual(result["hours"][0]["time"], first)
                self.assertEqual(result["hours"][-1]["time"], last)

    def test_short_forecast_returns_available_hours(self):
        result = weather.parse_weather(SAMPLE)
        self.assertEqual(len(result["hours"]), 13)
        self.assertEqual(result["hours"][-1]["time"], "23:00")

    def test_build_url(self):
        query = parse_qs(urlparse(weather.build_url(60.29, 25.04, "Europe/Helsinki")).query)
        self.assertEqual(query["latitude"], ["60.29"])
        self.assertEqual(query["timezone"], ["Europe/Helsinki"])
        self.assertEqual(query["forecast_days"], ["1"])
        self.assertEqual(query["forecast_hours"], ["25"])

    def test_unknown_code(self):
        self.assertEqual(weather.describe(None), ("", ""))
        self.assertEqual(weather.describe(1234), ("", ""))


if __name__ == "__main__":
    unittest.main()
