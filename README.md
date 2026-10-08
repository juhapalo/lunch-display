# lunch-display

Raspberry Pi 1B driven lunch display. Shows full screen (no browser frames,
toolbars or mouse pointer):

* **Vantaa weather** – current conditions, today's min/max and the next 24 hours
  in two-hour steps (00:00, 02:00, etc.)
  (from the free [Open-Meteo](https://open-meteo.com/) API, no API key needed)
* **Lunch menu** of
  * Flying Dylan
  * Ravintola Factory Aviapolis
  * Huili Kehä 3 Vantaa
* **Extra web pages** of your choice, shown one after another, each for an
  adjustable number of seconds.

The server is plain Python 3.9+ (standard library only – nothing to `pip install`),
so it runs comfortably on the single-core ARMv6 Pi 1B. The screen is drawn by
the very light [surf](https://surf.suckless.org/) browser under
`matchbox-window-manager`, which shows every window maximised with no title bar.

## Installation on the Raspberry Pi

1. Flash **Raspberry Pi OS Lite (32-bit)** to the SD card, enable network and
   SSH, and boot the Pi with the display attached.
2. On the Pi:

   ```sh
   sudo apt-get install -y git
   git clone https://github.com/juhapalo/lunch-display.git
   cd lunch-display
   ./deploy/install.sh
   sudo reboot
   ```

`install.sh` installs the needed packages, creates `config.json` from
`config.example.json`, installs the `lunch-display` systemd service (the data
server on port 8080), enables console auto-login and starts the kiosk
(`deploy/kiosk.sh`) on tty1 at boot.

To use Chromium instead of surf set `LUNCH_DISPLAY_BROWSER=chromium-browser`
in `~/.bash_profile` before the kiosk start lines (Chromium is much heavier on
a Pi 1B).

## Adding web pages / adjusting times

Open the admin page `http://<pi-address>:8080/admin`:

* `dashboard` is the built-in weather + lunch view.
* Add any `http(s)://` address, set how many seconds it is shown, reorder with
  ↑/↓, disable with the checkbox, and press **Tallenna** (save).
* Changes are picked up at the next page change – no restart needed.

By default the admin page only works on the Pi itself. To use it from
another computer set a password in `config.json` and restart the service
(`sudo systemctl restart lunch-display`):

```json
"admin_password": "choose-a-password"
```

The browser then asks for a user name (anything) and that password.

> Pages are shown inside a full-screen frame. Some sites forbid being framed
> (`X-Frame-Options` / `Content-Security-Policy`); such pages stay blank.

## Configuration (`config.json`)

| key | meaning |
| --- | --- |
| `listen_host`, `listen_port` | address of the local server (default `0.0.0.0:8080`) |
| `admin_password` | password for the admin page from other machines (empty = only localhost) |
| `location` | weather location name, coordinates and time zone (default Vantaa) |
| `weather_refresh_minutes` | how often the weather is refreshed |
| `menu_refresh_minutes` | how often the lunch menus are refreshed |
| `restaurants` | list of `{"name": ..., "urls": [...]}`; URLs are tried in order |
| `rotation` | list of `{"url": ..., "duration": seconds, "enabled": true}` |

Lunch menus show today on Monday–Friday before **14:00**, then switch to the
next Monday–Friday date. Friday from 14:00 and weekends show the upcoming
Monday. Working days here mean Monday–Friday; public holidays are **not**
automatically excluded. The cutoff uses `location.timezone` (default
`Europe/Helsinki`), including daylight saving time, not the Pi's local timezone.
The server checks for target-date changes every 30 seconds regardless of
`menu_refresh_minutes`; the dashboard polls every minute.
Weather and the clock/calendar stay on today, while each lunch panel labels
the fetched target date (also exposed as `menus_date` in `/api/data`).
If that menu is not published, the panel reports it unavailable for that date
instead of using an explicitly dated previous week's menu.

Python's standard-library `zoneinfo` requires system timezone data (`tzdata`,
normally included in Raspberry Pi OS). Invalid/missing timezone data is an
error, never a silent fallback to the host timezone. If necessary, install it
with `sudo apt-get install tzdata`.

Lunch menus are read from the restaurants' web pages: the page is turned into
text and the target section is picked from between the weekday headings
("Torstaina 8.10.", "Torstai", "TO 8.10.", "Thursday" …).
Dates, week numbers and date ranges are checked when provided; undated weekly
menus without any week/date context are treated as recurring menus, so their
freshness cannot be verified automatically. If a restaurant changes its web
site, just point its `urls` to a page that lists the week's menu (for example
the restaurant's page on lounaat.info).
Existing `config.json` restaurant URL overrides are preserved. Flying Dylan's
configured lounaat.info fallback uses the same improved parser; no URL
migration or browser automation is required.

## Updating the raspberry from main-repo
cd ~/lunch-display
git pull origin main
sudo systemctl restart lunch-display

## Development

Run locally (any computer with Python 3.9+):

```sh
python3 -m lunch_display --config config.json   # http://localhost:8080/
python3 -m unittest discover -s tests -t .
```

| URL | content |
| --- | --- |
| `/` | the rotating full-screen display |
| `/dashboard` | weather + lunch view |
| `/admin` | rotation settings |
| `/api/data`, `/api/rotation` | JSON data |
