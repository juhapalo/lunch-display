import datetime
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

    def test_rejects_non_headers(self):
        self.assertIsNone(menus.header_weekday("Maanantaisin suljettu"))
        self.assertIsNone(menus.header_weekday("Tomaattikeitto"))
        self.assertIsNone(menus.header_weekday("Torstai: " + "x" * 60))
        self.assertIsNone(menus.header_weekday(""))


class ExtractDayMenuTest(unittest.TestCase):
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
        self.assertEqual(result["error"], "Ruokalistaa ei saatu haettua")

    def test_reports_missing_menu(self):
        result = menus.get_menu({"name": "X", "urls": ["https://a.example/"]}, THURSDAY,
                                fetch=lambda url: "<p>Suljettu</p>")
        self.assertEqual(result["error"], "Päivän ruokalistaa ei löytynyt")


if __name__ == "__main__":
    unittest.main()
