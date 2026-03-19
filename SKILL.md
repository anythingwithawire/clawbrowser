---
name: clawbrowser
description: 'Control ClawBrowser — a stealth Qt WebEngine browser with a localhost HTTP API. Use when you need to browse the web, log in to sites, click buttons, fill forms, take screenshots, or scrape content WITHOUT being detected as a bot. Prefer over agent-browser/Playwright when bot detection is a concern (REA, LinkedIn, Kasada-protected sites). NOT for: simple web fetches (use web_fetch), public APIs (use exec/curl).'
metadata:
  {
    "openclaw": { "emoji": "🌐" }
  }
---

# ClawBrowser Skill

ClawBrowser is a real Chromium browser (PyQt6 WebEngine) with a localhost HTTP control API.
No CDP, no Selenium, no automation flags — invisible to bot detection.

## Location

- **Source:** `~/tools/clawbrowser/` (or clone from https://github.com/anythingwithawire/clawbrowser)
- **API port:** 8765 (default), configurable via `CLAW_PORT`
- **CLI wrapper:** `~/tools/clawbrowser/claw.sh`
- **Data/cookies:** `~/.clawbrowser/` (persistent — logins survive restarts)
- **Python:** Must use `/usr/bin/python3` (3.10) — NOT linuxbrew python3 (3.14, no PyQt6)

## Start the Browser

```bash
DISPLAY=:1 /usr/bin/python3 ~/tools/clawbrowser/browser.py &
sleep 4  # wait for Qt + API to initialise
```

Check it's up:
```bash
curl -sf http://127.0.0.1:8765/status
```

## CLI Commands (claw.sh)

```bash
CLAW=~/tools/clawbrowser/claw.sh

$CLAW status                        # url, title, tabs, ads blocked
$CLAW go https://example.com        # navigate
$CLAW shot /tmp/shot.png            # screenshot
$CLAW dom 10000                     # page HTML (truncated)
$CLAW text 5000                     # visible text only
$CLAW click "button.submit"         # click by CSS selector
$CLAW click 450,300                 # click by coordinates
$CLAW type "#username" "gareth"     # type into input
$CLAW js "document.title"           # run JavaScript
$CLAW links                         # list all links
$CLAW forms                         # list all form inputs
$CLAW wait 3                        # wait 3s then show status
```

## HTTP API (direct curl)

```bash
BASE=http://127.0.0.1:8765

curl -sf $BASE/status
curl -sf -X POST $BASE/navigate -H "Content-Type: application/json" -d '{"url":"https://example.com"}'
curl -sf $BASE/screenshot -o /tmp/shot.png
curl -sf $BASE/dom
curl -sf -X POST $BASE/eval -H "Content-Type: application/json" -d '{"script":"document.title"}'
curl -sf -X POST $BASE/click -H "Content-Type: application/json" -d '{"selector":"button"}'
curl -sf -X POST $BASE/click -H "Content-Type: application/json" -d '{"x":100,"y":200}'
curl -sf -X POST $BASE/type -H "Content-Type: application/json" -d '{"selector":"#q","text":"hello"}'
```

## Typical Workflow

```bash
# 1. Start browser (if not already running)
DISPLAY=:1 /usr/bin/python3 ~/tools/clawbrowser/browser.py &
sleep 4

CLAW=~/tools/clawbrowser/claw.sh

# 2. Navigate
$CLAW go https://site.com/login

# 3. Screenshot to see what's on screen (send to vision model)
$CLAW shot /tmp/shot.png

# 4. Fill and submit login form
$CLAW type "#email" "user@example.com"
$CLAW type "#password" "secret"
$CLAW click "button[type=submit]"
$CLAW wait 3

# 5. Scrape content
$CLAW text 10000
```

## Notes

- **Logins persist** — cookies saved to `~/.clawbrowser/storage/`. Log in once, stays logged in.
- **Screenshot → vision model** is the most reliable way to understand the current page state.
- If a CSS selector doesn't work, fall back to coordinates from the screenshot.
- GBM warning on startup ("Fallback to Vulkan rendering") is harmless — ignore it.
- Kill with: `pkill -f "browser.py"`
- Check if running: `curl -sf http://127.0.0.1:8765/status && echo "running" || echo "not running"`
