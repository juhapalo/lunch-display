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
**Chromium** in kiosk mode (best support for modern HTML pages) under
`matchbox-window-manager`, which shows every window maximised with no title bar.
Every rotation page is opened **once in its own Chromium tab**; a page change
only switches the visible tab, so pages are not reloaded at every page change.
An **x11vnc** VNC server shares the display for remote viewing/maintenance.

> **Pi 1B / ARMv6 note:** Chromium is heavy for a 512 MB single-core Pi. The
> Raspberry Pi OS (armhf) Chromium has had ARMv6 builds that failed with
> “Illegal instruction”
> ([RPi-Distro/chromium#21](https://github.com/RPi-Distro/chromium/issues/21),
> later fixed), and the Raspberry Pi developers describe it as very slow on
> Pi 1/Zero. Keep the number of pages small. If Chromium does not run on your
> image, use the lighter surf fallback (see below).

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

`install.sh` installs the needed packages (X, Chromium – `chromium-browser`
on Raspberry Pi OS, otherwise `chromium` – and `x11vnc`), creates
`config.json` from `config.example.json`, installs the `lunch-display` systemd
service (the data server on port 8080) and the `lunch-display-vnc` service,
enables console auto-login and starts the kiosk (`deploy/kiosk.sh`) on tty1 at
boot. Set `vnc_password` (see [VNC](#vnc-remote-access)) before running the
installer, or restart the VNC service after setting it.

### Browser and page rotation

`deploy/kiosk.sh` starts Chromium with `--kiosk --noerrdialogs
--disable-infobars --disable-session-crashed-bubble
--check-for-update-interval=31536000`, low-memory/low-end flags
(`--enable-low-end-device-mode`, `--disable-gpu`, `--disable-smooth-scrolling`,
`--disable-low-res-tiling`, `--disable-composited-antialiasing`, a small disk
cache, no background networking/updates/sync), a dedicated profile in
`~/.config/lunch-display-chromium`, and `--remote-debugging-port=9222`.
Screen blanking and DPMS are switched off with `xset`, and the mouse pointer is
hidden. Chromium is restarted automatically if it exits.

The `lunch-display` service controls the tabs through the Chrome DevTools
Protocol on `127.0.0.1:9222` (`/json/list`, `/json/new`, `/json/activate/<id>`):

* every enabled page is opened once in its own tab and kept alive; the rotation
  only activates the next tab (no reload);
* pages with a `refresh` interval are reloaded periodically, while hidden when
  more than one page is configured;
* a closed tab is reopened, a tab that stops responding (crashed renderer) is
  replaced, and after a Chromium restart all tabs are opened again;
* other tabs (e.g. pop-ups) are closed.

The DevTools port is only reachable from the Pi itself, but any local process
can control the browser through it. Optional environment variables (set them in
`~/.bash_profile` before the kiosk block): `LUNCH_DISPLAY_BROWSER`
(`chromium-browser`/`chromium`, default: whichever is installed),
`LUNCH_DISPLAY_URL` (first page) and `LUNCH_DISPLAY_CHROMIUM_FLAGS` (extra
flags, e.g. `--renderer-process-limit=2` to save memory).

**surf fallback:** if Chromium is unusable on your Pi, run
`sudo apt-get install surf` and set `export LUNCH_DISPLAY_BROWSER=surf`. surf
shows the `/` page, which keeps every page in its own persistent iframe (no
reload at page changes either), but sites that forbid framing stay blank there.

### VNC (remote access)

`x11vnc` shares the kiosk display (`:0`) and is started at boot by the
`lunch-display-vnc` systemd service (it waits/retries until X is running). It
always requires a password and does not start while `vnc_password` is empty.
Configure it in `config.json`:

```json
"vnc_enabled": true,
"vnc_port": 5900,
"vnc_password": "choose-a-password"
```

then apply the change with `./deploy/install.sh` (or just
`sudo systemctl restart lunch-display-vnc` when only the port/password changed).
The password must be printable ASCII without spaces, must not start with `#`
and must not contain `__`; VNC only uses its **first 8 characters**. The password
is passed to x11vnc in a private, temporary file, never on the command line.
`"vnc_enabled": false` (or `"frontend_browser_enabled": false`, which has no
local display to share) stops and disables the service when the installer is
rerun.

Connect with any VNC viewer (RealVNC Viewer, TigerVNC, Remmina …) to
`<pi-address>:5900` (or the configured port; viewers that use display numbers
need `<pi-address>::5900`) and enter the password. Check the server with
`systemctl status lunch-display-vnc` / `journalctl -u lunch-display-vnc`.
VNC traffic is not encrypted: use it only in a trusted network, or tunnel it
over SSH (`ssh -L 5900:localhost:5900 pi@<pi-address>`, then connect to
`localhost:5900`).

### Use the Pi only as a VNC viewer (no local browser)

Set the JSON boolean `"frontend_browser_enabled": false` in the repository's
`config.json` (not the string `"false"`). The default is `true`, including when
the key is absent in an older configuration.

For an existing installation, after updating the repository:

```sh
cd ~/lunch-display
# Edit config.json and set frontend_browser_enabled to false.
./deploy/install.sh
sudo systemctl restart lunch-display
sudo reboot
```

Rerunning the installer migrates the original lunch-display kiosk block in
`~/.bash_profile` to check the setting **before** starting X. Unrelated profile
content is preserved. Restart the service after editing its configuration;
reboot to stop an already-running local kiosk. Changing the setting does not
terminate an active browser automatically. Later login/startup checks use the
new value. A direct `deploy/kiosk.sh` invocation also checks it before doing
anything with X or waiting for the server.

For a fresh installation, copy `config.example.json` to `config.json` and set
the flag before running the installer. When disabled, the installer skips
X/browser packages and console auto-login setup; existing packages and
auto-login settings are not removed. Startup reads `config.json` beside the
repository, independent of the working directory. Invalid/unreadable startup
configuration produces an error and does not launch the kiosk.

The Python service and all HTTP routes remain available. On the remote machine
whose desktop the Pi views over VNC, open `http://<pi-address>:8080/` for page
rotation, or `http://<pi-address>:8080/dashboard` for just weather and lunch.
The admin page remains at `/admin`, with the existing remote-password rules.
Configure your VNC viewer separately: in this mode the project does not install
or start a VNC server/viewer (the `lunch-display-vnc` server shares the local
kiosk display, which is disabled here), the service does not control any
browser tabs, and the disabled kiosk does not take over the tty session.

## Adding web pages / adjusting times

Open the admin page `http://<pi-address>:8080/admin`:

* `dashboard` is the built-in weather + lunch view.
* Add any `http(s)://` address, set how many seconds it is shown, reorder with
  ↑/↓, disable with the checkbox, and press **Tallenna** (save).
* **Päivitys (s)** (refresh) reloads the page periodically, e.g. `600` = every
  10 minutes (minimum 30 s, `0` = never). Pages are otherwise loaded only once.
  The built-in `dashboard` updates its data by itself.
* Changes are picked up at the next page change – no restart needed.

By default the admin page only works on the Pi itself. To use it from
another computer set a password in `config.json` and restart the service
(`sudo systemctl restart lunch-display`):

```json
"admin_password": "choose-a-password"
```

The browser then asks for a user name (anything) and that password.

> On the Pi, pages are shown in real Chromium tabs, so sites that forbid
> framing work too. The `/` page (used by the surf fallback or a remote
> browser) shows pages inside full-screen frames; there sites that forbid being
> framed (`X-Frame-Options` / `Content-Security-Policy`) stay blank.

## Configuration (`config.json`)

| key | meaning |
| --- | --- |
| `listen_host`, `listen_port` | address of the local server (default `0.0.0.0:8080`) |
| `admin_password` | password for the admin page from other machines (empty = only localhost) |
| `frontend_browser_enabled` | JSON boolean; start the Pi's local X/browser kiosk (default `true`); does not disable HTTP routes |
| `vnc_enabled` | JSON boolean; share the kiosk display with x11vnc (default `true`) |
| `vnc_port` | VNC server port (default `5900`) |
| `vnc_password` | VNC password, required for the VNC server to start (default empty) |
| `location` | weather location name, coordinates and time zone (default Vantaa) |
| `weather_refresh_minutes` | how often the weather is refreshed |
| `menu_refresh_minutes` | how often the lunch menus are refreshed |
| `restaurants` | list of `{"name": ..., "urls": [...]}`; URLs are tried in order |
| `rotation` | list of `{"url": ..., "duration": seconds, "enabled": true}`, optionally with `"refresh": seconds` (periodic reload, `0`/absent = never) |

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

Huili's reported daily-page layout places a dated weekday before a separate
“Päivän lounas 13.90 €” heading. Previously that heading ended extraction before
the dishes. The parser now skips this title within a dated menu and stops at
“Katso koko viikon lounaslista”/download labels; opening-hour time ranges are
not menu items. Dietary markers are retained. The reported `perjantai 9.10.`
section cannot supply food for Monday 12.10.2026 or another target date.

Live-source limitation for this fix: direct retrieval of the official Huili
URL failed with DNS resolution errors in the development environment, and the
browser tool was unavailable. The offline fixture is a sanitized reconstruction
of the previously inspected page's text order, with synthetic dishes, not a
verified capture of current HTML. Regression tests reproduce the heading
failure and exercise stale dates and menu boundaries. The weekly download URL,
its format, and any embedded target-date data could not be independently
verified, so no speculative fallback or new dependency was added.

## Updating the raspberry from main-repo
cd ~/lunch-display
git pull origin main
sudo systemctl restart lunch-display

When updating from a version that used surf, rerun `./deploy/install.sh` once
(installs Chromium, x11vnc and the VNC service; set `vnc_password` in
`config.json` first) and reboot.

## Development

Run locally (any computer with Python 3.9+):

```sh
python3 -m lunch_display --config config.json --no-tabs   # http://localhost:8080/
python3 -m unittest discover -s tests -t .
```

`--no-tabs` keeps the server from taking over the tabs of a Chromium/Chrome
that happens to listen on DevTools port 9222 on your computer.

| URL | content |
| --- | --- |
| `/` | the rotating full-screen display with persistent iframes (surf fallback / remote browsers) |
| `/dashboard` | weather + lunch view |
| `/admin` | rotation settings |
| `/api/data`, `/api/rotation` | JSON data |
