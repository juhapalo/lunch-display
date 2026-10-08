"""Lunch menu scraping.

Finnish lunch restaurant pages almost always list the week's menu as
sections that start with a weekday heading ("Torstai 8.10.", "TORSTAI",
"Thursday" ...). Instead of depending on the exact HTML structure of each
site (which changes often), the page is converted to plain text lines and
today's section is picked out from between the weekday headings.
"""

import datetime
import re
from html.parser import HTMLParser

from .fetch import fetch_text

WEEKDAYS_FI = [
    "maanantai",
    "tiistai",
    "keskiviikko",
    "torstai",
    "perjantai",
    "lauantai",
    "sunnuntai",
]
WEEKDAYS_EN = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]
WEEKDAY_ABBR_FI = ["ma", "ti", "ke", "to", "pe", "la", "su"]

MAX_HEADER_LENGTH = 40
MAX_ITEMS = 15
STOP_MARKERS = ("©", "copyright", "evästeet", "tietosuoja")

_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl",
    "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
    "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p",
    "pre", "section", "table", "td", "th", "tr", "ul",
}
_SKIP_TAGS = {"script", "style", "noscript", "svg", "head", "template", "iframe"}
_ABBR_RE = re.compile(r"^(ma|ti|ke|to|pe|la|su)\.?\s+\d{1,2}\.\s?\d{1,2}\b")
_SPACE_RE = re.compile(r"\s+")


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def html_to_lines(html):
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    lines = []
    for line in "".join(parser.parts).split("\n"):
        line = _SPACE_RE.sub(" ", line).strip()
        if line:
            lines.append(line)
    return lines


def header_weekday(line):
    """Return the weekday index (0=Monday) if the line is a weekday heading."""
    text = line.strip().lower()
    if not text or len(text) > MAX_HEADER_LENGTH:
        return None
    for names in (WEEKDAYS_FI, WEEKDAYS_EN):
        for index, name in enumerate(names):
            if text.startswith(name) and (
                len(text) == len(name) or not text[len(name)].isalpha()
            ):
                return index
    match = _ABBR_RE.match(text)
    if match:
        return WEEKDAY_ABBR_FI.index(match.group(1))
    return None


def _date_tokens(day):
    return ("%d.%d." % (day.day, day.month), "%d.%d" % (day.day, day.month),
            "%02d.%02d." % (day.day, day.month))


def extract_day_menu(lines, day, max_items=MAX_ITEMS):
    """Pick the lines that belong to the given date's menu section."""
    weekday = day.weekday()
    headers = [(i, header_weekday(line)) for i, line in enumerate(lines)]
    headers = [(i, wd) for i, wd in headers if wd is not None]
    dates = _date_tokens(day)

    best = None
    best_score = None
    for position, (index, wd) in enumerate(headers):
        if wd != weekday:
            continue
        end = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
        items = []
        for line in lines[index + 1:end]:
            lowered = line.lower()
            if any(marker in lowered for marker in STOP_MARKERS):
                break
            if len(line) < 2 or (items and items[-1] == line):
                continue
            items.append(line)
            if len(items) >= max_items:
                break
        if not items:
            continue
        header = lines[index].replace(" ", "")
        has_date = any(token in header for token in dates)
        score = (has_date, len(items))
        if best_score is None or score > best_score:
            best, best_score = items, score
    return best or []


def get_menu(restaurant, day=None, fetch=fetch_text):
    """Fetch today's menu for a restaurant config entry.

    Tries the configured URLs in order and returns the first one that
    contains a menu for the day.
    """
    day = day or datetime.date.today()
    urls = restaurant.get("urls") or []
    result = {
        "name": restaurant.get("name", ""),
        "url": urls[0] if urls else "",
        "items": [],
        "error": None,
    }
    errors = []
    for url in urls:
        try:
            lines = html_to_lines(fetch(url))
        except Exception as exc:  # network errors, bad HTML, ...
            errors.append("%s: %s" % (url, exc))
            continue
        items = extract_day_menu(lines, day)
        if items:
            result["items"] = items
            result["url"] = url
            return result
    if errors and len(errors) == len(urls):
        result["error"] = "Ruokalistaa ei saatu haettua"
    else:
        result["error"] = "Päivän ruokalistaa ei löytynyt"
    result["details"] = errors
    return result
