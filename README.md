# ClawBrowser

A stealth browser with a localhost HTTP control API, built for AI agents.

No Selenium. No Playwright. No Chrome DevTools Protocol. No automation fingerprints.

Just PyQt6 WebEngine (real Chromium) + a simple REST API on localhost.

## Why

Standard automation tools (Selenium, Playwright, CDP) leave detectable signatures. Sites like REA, LinkedIn, and anything running Kasada/PerimeterX will block them. ClawBrowser presents as a normal user-launched Chromium process — because it is one.

Built for AI agents that need to browse the web without getting blocked. Also usable as a fast, no-telemetry browser for humans.

## Install

```bash
pip install PyQt6 PyQt6-WebEngine
```

## Run

```bash
python browser.py              # default port 8765
python browser.py --port 9000  # custom port
CLAW_PORT=9000 python browser.py
```

## Control via CLI

```bash
chmod +x claw.sh

claw.sh status                   # browser status + ads blocked
claw.sh go https://example.com   # navigate
claw.sh shot [file]              # screenshot (default: /tmp/claw_shot.png)
claw.sh dom [chars]              # page HTML
claw.sh text [chars]             # visible text only
claw.sh click "button.submit"    # click by CSS selector
claw.sh click 450,300            # click by coordinates
claw.sh type "#search" "hello"   # type into input
claw.sh js "document.title"      # run JavaScript
claw.sh links                    # list all links
claw.sh forms                    # list all form elements
claw.sh tabs                     # list open tabs
claw.sh tab new https://...      # open new tab
claw.sh wait [secs]              # wait then show status
```

## HTTP API

All endpoints on `http://127.0.0.1:8765` (or your configured port):

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| GET | `/status` | — | Browser state |
| POST | `/navigate` | `{"url": "..."}` | Navigate |
| GET | `/screenshot` | — | PNG bytes |
| GET | `/dom` | — | `{"html": "..."}` |
| POST | `/eval` | `{"script": "..."}` | Run JS, returns `{"result": ...}` |
| POST | `/click` | `{"selector": "..."}` or `{"x": n, "y": n}` | Click |
| POST | `/type` | `{"selector": "...", "text": "..."}` | Type |
| GET | `/links` | — | All `<a>` elements |
| GET | `/forms` | — | All form inputs |
| GET | `/tabs` | — | Tab list |
| POST | `/tab/new` | `{"url": "..."}` | New tab |
| POST | `/tab/close` | `{"index": n}` | Close tab |
| POST | `/tab/switch` | `{"index": n}` | Switch tab |

## Ad Blocking

Domain blocklist at `~/.clawbrowser/blocked_domains.txt` — one domain per line.

## Features

- Real Chromium rendering via Qt WebEngine
- Tabbed UI (usable by humans too)
- Ad blocking via domain blocklist
- Bookmarks + history
- No telemetry, no Google sync, no crash reporting
- No webdriver flags — invisible to bot detection
- Localhost-only API (not accessible from network)

## Requirements

- Python 3.10+
- PyQt6
- PyQt6-WebEngine
- Linux (tested on Ubuntu/Pop!_OS). macOS should work. Windows untested.

## Notes

- Requires Python 3.10–3.12 (PyQt6-WebEngine not yet available for 3.13+)
- On Linux with multiple Python installs, use `/usr/bin/python3` explicitly if the default python3 is newer
- Tested on Ubuntu 22.04 / Pop!_OS
