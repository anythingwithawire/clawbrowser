# ClawBrowser

A stealth browser with a localhost HTTP control API, built for AI agents.

No Selenium. No Playwright. No Chrome DevTools Protocol. No automation fingerprints.

Just PyQt6 WebEngine (real Chromium) + a simple REST API on localhost.

## Why

Standard automation tools (Selenium, Playwright, CDP) leave detectable signatures. Sites like REA, LinkedIn, and anything running Kasada/PerimeterX will block them. ClawBrowser presents as a normal user-launched Chromium process — because it is one.

Built for AI agents that need to browse the web without getting blocked. Also usable as a fast, no-telemetry browser for humans.

## Install

### Requirements

- Python **3.10–3.12** (PyQt6-WebEngine is not yet available for 3.13+)
- Linux (tested on Ubuntu 22.04 / Pop!_OS). macOS should work. Windows untested.

### Check your Python version

```bash
python3 --version
```

If you're on 3.13+ (e.g. via Homebrew), find your system Python:

```bash
ls /usr/bin/python3*
# Use /usr/bin/python3 explicitly below
```

### Install dependencies

```bash
pip install PyQt6 PyQt6-WebEngine
# or explicitly:
/usr/bin/python3 -m pip install PyQt6 PyQt6-WebEngine
```

### Clone

```bash
git clone https://github.com/anythingwithawire/clawbrowser
cd clawbrowser
chmod +x claw.sh
```

## Run

```bash
python3 browser.py              # default port 8765
python3 browser.py --port 9000  # custom port
CLAW_PORT=9000 python3 browser.py

# Linux with multiple Python versions — use system Python explicitly:
/usr/bin/python3 browser.py
```

On Linux, a `DISPLAY` must be set (for headless/server use, set `DISPLAY=:1` if you have a virtual framebuffer):

```bash
DISPLAY=:1 /usr/bin/python3 browser.py &
sleep 4  # wait for Qt + API to initialise
```

Check it's up:

```bash
curl -sf http://127.0.0.1:8765/status
```

## Control via CLI

```bash
./claw.sh status                   # browser status + ads blocked
./claw.sh go https://example.com   # navigate
./claw.sh shot [file]              # screenshot (default: /tmp/claw_shot.png)
./claw.sh dom [chars]              # page HTML
./claw.sh text [chars]             # visible text only
./claw.sh click "button.submit"    # click by CSS selector
./claw.sh click 450,300            # click by coordinates
./claw.sh type "#search" "hello"   # type into input
./claw.sh js "document.title"      # run JavaScript
./claw.sh links                    # list all links
./claw.sh forms                    # list all form elements
./claw.sh tabs                     # list open tabs
./claw.sh tab new https://...      # open new tab
./claw.sh wait [secs]              # wait then show status
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
| GET | `/bookmarks` | — | Bookmark list |
| POST | `/bookmarks` | `{"url": "...", "title": "..."}` | Add bookmark |
| DELETE | `/bookmarks` | `{"url": "..."}` | Remove bookmark |
| GET | `/history` | `?q=&limit=` | Search history |

## Ad Blocking

Domain blocklist at `~/.clawbrowser/blocked_domains.txt` — one domain per line.

## OpenClaw Integration

If you're using [OpenClaw](https://github.com/openclaw/openclaw), drop `SKILL.md` into your workspace skills directory:

```bash
mkdir -p ~/.openclaw/workspace/skills/clawbrowser
cp SKILL.md ~/.openclaw/workspace/skills/clawbrowser/
```

OpenClaw will auto-discover the skill and use ClawBrowser when bot detection is a concern.

## Features

- Real Chromium rendering via Qt WebEngine
- Tabbed UI (usable by humans too)
- Ad blocking via domain blocklist
- Bookmarks + history (persisted to `~/.clawbrowser/`)
- Logins persist across restarts (cookies in `~/.clawbrowser/storage/`)
- No telemetry, no Google sync, no crash reporting
- No webdriver flags — invisible to bot detection
- Localhost-only API (not accessible from network)

## Notes

- If `browser.py` is already running, `claw.sh` will connect to it. No need to restart.
- Kill with: `pkill -f "browser.py"`
- GBM/Vulkan warnings on startup are harmless — ignore them.
- Screenshot → vision model is the most reliable way to understand page state when selectors fail.
