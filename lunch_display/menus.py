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
WEEKDAYS_INFLECTED = [
    "maanantaina", "tiistaina", "keskiviikkona", "torstaina",
    "perjantaina", "lauantaina", "sunnuntaina",
]

MAX_HEADER_LENGTH = 40
MAX_ITEMS = 15
STOP_MARKERS = ("©", "copyright", "evästeet", "tietosuoja")

_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl",
    "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
    "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p",
    "pre", "section", "table", "td", "th", "tr", "ul",
}
_SKIP_TAGS = {"script", "style", "noscript", "svg", "head", "template", "iframe",
              "nav", "footer", "aside"}
_CONTAINERS = {"div", "section", "article", "main", "table", "body"}
_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\.\s*(\d{1,2})(?!\d)"
                      r"(?:\.\s*(\d{4}|\d{2})(?!\d)|\.?)(?!\d)")
_PRICE_RE = re.compile(r"^\d+(?:[.,]\d{1,2})?\s*(?:€|eur|euroa)$", re.I)
_WEEK_RE = re.compile(r"\b(?:viikko|vko|week)\s*(\d{1,2})"
                      r"(?:\s*[/, ]\s*(\d{4}))?\b", re.I)
_RANGE_RE = re.compile(r"(\d{1,2}\.\s*\d{1,2}\.(?:\d{4})?)\s*[-–—]\s*"
                       r"(\d{1,2}\.\s*\d{1,2}\.(?:\d{4})?)")
_SPACE_RE = re.compile(r"\s+")


class _Line(str):
    def __new__(cls, text, scopes=(), heading=False):
        line = super().__new__(cls, text)
        line.scopes = scopes
        line.heading = heading
        return line


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines = []
        self.parts = []
        self._stack = []
        self._serial = 0
        self._skip_depth = 0

    def _flush(self):
        text = _SPACE_RE.sub(" ", "".join(self.parts)).strip()
        if text:
            self.lines.append(_Line(text, tuple(
                number for tag, number in self._stack if tag in _CONTAINERS),
                any(tag in {"h1", "h2", "h3", "h4", "h5", "h6"}
                    for tag, number in self._stack)))
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self._flush()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        if tag not in {"br", "hr", "img", "input", "meta", "link", "wbr", "source", "embed", "area"}:
            self._serial += 1
            self._stack.append((tag, self._serial))

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag):
        if tag in _BLOCK_TAGS:
            self._flush()
        if tag in _SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def html_to_lines(html):
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    parser._flush()
    return parser.lines


def header_weekday(line):
    """Return the weekday index (0=Monday) if the line is a weekday heading."""
    text = line.strip().lower()
    if not text or len(text) > MAX_HEADER_LENGTH:
        return None
    for names in (WEEKDAYS_FI, WEEKDAYS_EN, WEEKDAYS_INFLECTED, WEEKDAY_ABBR_FI):
        for index, name in enumerate(names):
            if not text.startswith(name):
                continue
            tail = text[len(name):].strip()
            if names is WEEKDAY_ABBR_FI:
                tail = tail.lstrip(".").strip()
                if not tail:
                    continue
            tail = tail.lstrip(":–-").strip()
            if not tail or _DATE_RE.fullmatch(tail):
                return index
    return None


def _heading_date(line, day):
    match = _DATE_RE.search(line)
    if not match:
        return None
    date, month, year = match.groups()
    if year:
        year = int(year)
        if year < 100:
            year += 2000
    else:
        candidates = []
        for year in (day.year - 1, day.year, day.year + 1):
            try:
                candidates.append(datetime.date(year, int(month), int(date)))
            except ValueError:
                pass
        return min(candidates, key=lambda value: abs((value - day).days)) if candidates else False
    try:
        return datetime.date(year, int(month), int(date))
    except ValueError:
        return False


def _section_end(lines, index, end):
    scopes = getattr(lines[index], "scopes", ())
    # A heading-only wrapper is not the menu container.
    for scope in reversed(scopes):
        if index + 1 < end and scope in getattr(lines[index + 1], "scopes", ()):
            for following in range(index + 1, end):
                if scope not in getattr(lines[following], "scopes", ()):
                    return following
            break
    return end


def _week_matches(lines, index, headers, day):
    for line in reversed(lines[:index + 1]):
        match = _RANGE_RE.search(line)
        if match:
            start, end = [_heading_date(value, day) for value in match.groups()]
            return bool(start and end and start <= day <= end)
        match = _WEEK_RE.search(line)
        if match:
            week, year = match.groups()
            iso_year, iso_week, _ = day.isocalendar()
            return int(week) == iso_week and (not year or int(year) == iso_year)
    dated = [(abs(i - index), _heading_date(lines[i], day)) for i, wd in headers
             if _DATE_RE.search(lines[i])]
    if dated:
        reference = min(dated, key=lambda entry: entry[0])[1]
        if not reference:
            return False
        # An undated heading in an explicitly dated week belongs to that week.
        return reference - datetime.timedelta(days=reference.weekday()) == (
            day - datetime.timedelta(days=day.weekday()))
    return True


def extract_day_menu(lines, day, max_items=MAX_ITEMS):
    """Pick the lines that belong to the given date's menu section."""
    weekday = day.weekday()
    headers = [(i, header_weekday(line)) for i, line in enumerate(lines)]
    headers = [(i, wd) for i, wd in headers if wd is not None]

    best = None
    best_score = None
    for position, (index, wd) in enumerate(headers):
        if wd != weekday:
            continue
        date = _heading_date(lines[index], day)
        if date is not None and date != day:
            continue
        if not _week_matches(lines, index, headers, day):
            continue
        end = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
        end = _section_end(lines, index, end)
        items = []
        for line in lines[index + 1:end]:
            lowered = line.lower()
            if getattr(line, "heading", False) or any(marker in lowered for marker in STOP_MARKERS):
                break
            if len(line) < 2 or _PRICE_RE.fullmatch(line) or (items and items[-1] == line):
                continue
            items.append(line)
            if len(items) >= max_items:
                break
        if not items:
            continue
        score = (date is not None, len(items))
        if best_score is None or score > best_score:
            best, best_score = items, score
    return best or []


def unavailable_message(day):
    return "Ruokalistaa ei saatavilla päivälle %d.%d.%d." % (day.day, day.month, day.year)


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
        result["error"] = unavailable_message(day) + " Haku epäonnistui."
    else:
        result["error"] = unavailable_message(day)
    result["details"] = errors
    return result
