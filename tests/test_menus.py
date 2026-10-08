import datetime
import os
import unittest

from lunch_display import menus

LOUNAAT_STYLE = """
<html><head><title>Lounas</title><script>var x = "Torstai";</script></head>
<body>
<nav><a>Maanantai</a><a>Tiistai</a><a>Keskiviikko</a><a>Torstai</a><a>Perjantai</a></nav>
<div class="menu">
  <h3>Keskiviikko 7.10.</h3>
  <p>Pinaattikeitto (L, G)</p>
  <h3>Torstai 8.10.</h3>
  <ul><li>Hernekeitto &amp; pannukakku</li><li>Pannupihvit, perunamuusi (L, G)</li></ul>
  <p>Kasvisgratiini<br>Teriyakitofu (VE)</p>
  <h3>Perjantai 9.10.</h3>
  <p>Lohikeitto</p>
</div>
<footer>&copy; 2026 Ravintola</footer>
</body></html>
"""

TABLE_STYLE = """
<table>
<tr><th>MA 5.10.</th><td>Kalaa</td></tr>
<tr><th>TO 8.10.</th><td>Broileria</td><td>Kasvispata</td></tr>
<tr><th>PE 9.10.</th><td>Pizzaa</td></tr>
</table>
"""

ENGLISH_STYLE = """
<div><h2>Thursday</h2><p>Fish &amp; chips</p><p>Veggie wok</p>
<h2>Friday</h2><p>Burger</p><p>Privacy</p></div>
<p>Copyright Dylan</p>
"""

THURSDAY = datetime.date(2026, 10, 8)


class HtmlToLinesTest(unittest.TestCase):
    def test_skips_scripts_and_splits_blocks(self):
        lines = menus.html_to_lines(LOUNAAT_STYLE)
        self.assertNotIn('var x = "Torstai";', lines)
        self.assertNotIn("Lounas", lines)  # <head> content is skipped
        self.assertIn("Hernekeitto & pannukakku", lines)
        self.assertIn("Kasvisgratiini", lines)
        self.assertIn("Teriyakitofu (VE)", lines)


class HeaderWeekdayTest(unittest.TestCase):
    def test_recognises_headers(self):
        self.assertEqual(menus.header_weekday("Torstai 8.10."), 3)
        self.assertEqual(menus.header_weekday("MAANANTAI"), 0)
        self.assertEqual(menus.header_weekday("Friday"), 4)
        self.assertEqual(menus.header_weekday("TO 8.10."), 3)
        self.assertEqual(menus.header_weekday("ke 7.10"), 2)
        for index, name in enumerate(menus.WEEKDAYS_INFLECTED):
            self.assertEqual(menus.header_weekday(name.capitalize() + " 8.10."), index)
        for names in (menus.WEEKDAYS_FI, menus.WEEKDAYS_EN):
            for index, name in enumerate(names):
                self.assertEqual(menus.header_weekday(name), index)

    def test_rejects_non_headers(self):
        self.assertIsNone(menus.header_weekday("Maanantaisin suljettu"))
        self.assertIsNone(menus.header_weekday("Tomaattikeitto"))
        self.assertIsNone(menus.header_weekday("Torstai: " + "x" * 60))
        self.assertIsNone(menus.header_weekday(""))
        for text in ("Torstai on keittopäivä", "Perjantaina tarjoamme kalaa",
                     "Monday lunch special", "ma", "Torstaina 8.10. avoinna"):
            self.assertIsNone(menus.header_weekday(text))


class ExtractDayMenuTest(unittest.TestCase):
    def test_reconstructed_inflected_listing_and_final_section(self):
        path = os.path.join(os.path.dirname(__file__), "fixtures", "flying_dylan.html")
        with open(path, encoding="utf-8") as handle:
            lines = menus.html_to_lines(handle.read())
        self.assertEqual(menus.extract_day_menu(lines, THURSDAY),
                         ["Hernekeitto & pannukakku (L)", "Teriyakitofu, riisiä (VE, G)"])
        self.assertEqual(menus.extract_day_menu(lines, datetime.date(2026, 10, 9)),
                         ["Ylikypsää possua, perunamuusia (L, G)",
                          "Paahdettuja kasviksia (VE, G)"])
        self.assertEqual(menus.extract_day_menu(lines, datetime.date(2026, 10, 12)), [])

    def test_last_section_stops_at_container_without_footer_marker(self):
        html = ("<main><section><h3>Friday</h3><p>Fish (G)</p></section>"
                "<div>Nearby restaurant</div><p>Contact</p></main>")
        self.assertEqual(menus.extract_day_menu(menus.html_to_lines(html),
                                               datetime.date(2026, 10, 9)), ["Fish (G)"])

    def test_prices_do_not_consume_item_limit(self):
        lines = ["Torstai"] + ["13,50 €", "10 EUR"] * 20 + ["Ruoka (L, G)", "Tofu (VE)"]
        self.assertEqual(menus.extract_day_menu(lines, THURSDAY, max_items=2),
                         ["Ruoka (L, G)", "Tofu (VE)"])

    def test_explicit_dates_must_match_exactly(self):
        target = datetime.date(2026, 1, 1)
        for header in ("Torstai 11.1.", "Torstai 1.10.", "Torstai 1.1.2025",
                       "Torstai 01.01.2025", "Torstai 32.1."):
            with self.subTest(header=header):
                self.assertEqual(menus.extract_day_menu([header, "Stale food"], target), [])
        for header in ("Torstai 1.1.", "TO 01.01.2026", "Thursday 1.1.26"):
            self.assertEqual(menus.extract_day_menu([header, "Food"], target), ["Food"])

    def test_undated_headings_respect_week_context(self):
        monday = datetime.date(2026, 10, 12)
        for lines in (["Viikko 41 / 2026", "Maanantai", "Vanha ruoka"],
                      ["Maanantai", "Vanha ruoka", "Tiistai 6.10.", "Keitto"],
                      ["Viikko 42 / 2025", "Monday", "Old food"]):
            self.assertEqual(menus.extract_day_menu(lines, monday), [])
        self.assertEqual(menus.extract_day_menu(
            ["Viikko 42 / 2026", "Maanantai", "Uusi ruoka"], monday), ["Uusi ruoka"])
        self.assertEqual(menus.extract_day_menu(["Monday", "Undated food"], monday),
                         ["Undated food"])

    def test_date_range_context_and_year_rollover(self):
        monday = datetime.date(2026, 10, 12)
        self.assertEqual(menus.extract_day_menu(
            ["Lounas 5.10.–9.10.2026", "Maanantai", "Old food"], monday), [])
        self.assertEqual(menus.extract_day_menu(
            ["Lounas 12.10.–16.10.2026", "Maanantai", "Food"], monday), ["Food"])
        new_year = datetime.date(2026, 1, 1)
        self.assertEqual(menus.extract_day_menu(
            ["Maanantai 29.12.", "Food", "Torstai", "New year food"], new_year),
            ["New year food"])
        self.assertEqual(menus.extract_day_menu(
            ["Viikko 1 / 2025", "Torstai 1.1.", "Old food"], new_year), [])
        for label in ("Lounas 5.10.2025–9.10.", "Lounas 5.10.–9.10.2027"):
            self.assertEqual(menus.extract_day_menu(
                [label, "Torstaina", "Old food"], THURSDAY), [])
        for label in ("Lounas 29.12.2025–2.1.", "Lounas 29.12.–2.1.2026",
                      "Lounas 29.12.–2.1."):
            self.assertEqual(menus.extract_day_menu(
                [label, "Torstai", "New year food"], new_year), ["New year food"])

    def test_picks_todays_section_not_navigation(self):
        items = menus.extract_day_menu(menus.html_to_lines(LOUNAAT_STYLE), THURSDAY)
        self.assertEqual(items, [
            "Hernekeitto & pannukakku",
            "Pannupihvit, perunamuusi (L, G)",
            "Kasvisgratiini",
            "Teriyakitofu (VE)",
        ])

    def test_table_layout_with_abbreviations(self):
        items = menus.extract_day_menu(menus.html_to_lines(TABLE_STYLE), THURSDAY)
        self.assertEqual(items, ["Broileria", "Kasvispata"])

    def test_english_and_stop_markers(self):
        friday = datetime.date(2026, 10, 9)
        items = menus.extract_day_menu(menus.html_to_lines(ENGLISH_STYLE), friday)
        self.assertEqual(items, ["Burger", "Privacy"])
        thursday = menus.extract_day_menu(menus.html_to_lines(ENGLISH_STYLE), THURSDAY)
        self.assertEqual(thursday, ["Fish & chips", "Veggie wok"])

    def test_prefers_section_with_todays_date(self):
        lines = ["Torstai 1.10.", "Vanha ruoka", "Vanha 2", "Vanha 3",
                 "Torstai 8.10.", "Uusi ruoka"]
        self.assertEqual(menus.extract_day_menu(lines, THURSDAY), ["Uusi ruoka"])

    def test_no_menu_for_day(self):
        saturday = datetime.date(2026, 10, 10)
        self.assertEqual(menus.extract_day_menu(menus.html_to_lines(LOUNAAT_STYLE), saturday), [])


class GetMenuTest(unittest.TestCase):
    def test_configured_flying_dylan_fallback(self):
        from lunch_display.config import Config

        restaurant = Config(None).get("restaurants")[0]
        path = os.path.join(os.path.dirname(__file__), "fixtures", "flying_dylan.html")
        with open(path, encoding="utf-8") as handle:
            html = handle.read()
        fetched = []

        def fetch(url):
            fetched.append(url)
            return "<p>Embedded menu unavailable</p>" if url == restaurant["urls"][0] else html

        result = menus.get_menu(restaurant, THURSDAY, fetch=fetch)
        self.assertEqual(fetched, restaurant["urls"])
        self.assertEqual(result["url"], restaurant["urls"][1])
        self.assertEqual(result["items"],
                         ["Hernekeitto & pannukakku (L)", "Teriyakitofu, riisiä (VE, G)"])
        self.assertEqual(menus.get_menu(restaurant, datetime.date(2026, 10, 12),
                                       fetch=fetch)["items"], [])

    def test_falls_back_to_next_url(self):
        pages = {"https://a.example/": "<p>Ei listaa</p>", "https://b.example/": LOUNAAT_STYLE}
        restaurant = {"name": "Test", "urls": list(pages)}
        result = menus.get_menu(restaurant, THURSDAY, fetch=pages.__getitem__)
        self.assertEqual(result["url"], "https://b.example/")
        self.assertEqual(len(result["items"]), 4)
        self.assertIsNone(result["error"])

    def test_reports_fetch_errors(self):
        def broken(url):
            raise OSError("no network")

        result = menus.get_menu({"name": "X", "urls": ["https://a.example/"]}, THURSDAY, fetch=broken)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["error"], "Ruokalistaa ei saatavilla päivälle 8.10.2026. Haku epäonnistui.")

    def test_reports_missing_menu(self):
        result = menus.get_menu({"name": "X", "urls": ["https://a.example/"]}, THURSDAY,
                                fetch=lambda url: "<p>Suljettu</p>")
        self.assertEqual(result["error"], "Ruokalistaa ei saatavilla päivälle 8.10.2026.")


if __name__ == "__main__":
    unittest.main()
