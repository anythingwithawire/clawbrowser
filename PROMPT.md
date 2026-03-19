# ClawBrowser — Build Prompt

Drop this into any capable LLM (Claude, GPT-4, etc.) to rebuild ClawBrowser from scratch.

---

Build a stealth browser called ClawBrowser for AI agent use. It must have zero automation fingerprints — no Selenium, no Playwright, no Chrome DevTools Protocol. Just a real Chromium browser controlled via a localhost HTTP API.

**Stack:** Python 3.10+, PyQt6, PyQt6-WebEngine only. No external browser binary required.

**Requirements:**

1. **Browser window** — tabbed UI with address bar, usable by a human. Named profile "ClawBrowser". Persistent cookies/storage saved to `~/.clawbrowser/storage/`. Cache to `~/.clawbrowser/cache/`.

2. **Ad blocking** — URL request interceptor that blocks domains listed in `~/.clawbrowser/blocked_domains.txt` (one domain per line).

3. **HTTP API** on `http://127.0.0.1:8765` (port configurable via `CLAW_PORT` env var), running in a background thread. Endpoints:
   - `GET /status` → `{url, title, tab_count, ads_blocked}`
   - `POST /navigate` `{url}` → navigate active tab
   - `GET /screenshot` → raw PNG bytes
   - `GET /dom` → `{html}` of current page
   - `POST /eval` `{script}` → run JS, return `{result}`
   - `POST /click` `{selector}` or `{x, y}` → click element or coords
   - `POST /type` `{selector, text}` → type into element
   - `GET /links` → list of `{text, href}`
   - `GET /forms` → list of `{tag, type, name, id, placeholder, value}`
   - `GET /tabs` → list of `{index, title, url, active}`
   - `POST /tab/new` `{url}` → open new tab
   - `POST /tab/close` `{index}` → close tab
   - `POST /tab/switch` `{index}` → switch active tab
   - `GET /bookmarks` → list bookmarks
   - `POST /bookmarks` `{url, title}` → add bookmark
   - `DELETE /bookmarks` `{url}` → remove bookmark
   - `GET /history?q=&limit=` → search history

4. **Bookmarks + history** persisted as JSON to `~/.clawbrowser/bookmarks.json` and `~/.clawbrowser/history.json`.

5. **Shell wrapper `claw.sh`** — bash script that curls the API with friendly subcommands: `status`, `go <url>`, `shot [file]`, `dom [chars]`, `text [chars]`, `click <selector|x,y>`, `type <sel> <text>`, `js <script>`, `links`, `forms`, `tabs`, `tab new|close|switch`, `bookmarks`, `bookmark add|del`, `history [query]`, `wait [secs]`.

6. **No telemetry.** No Google services. No crash reporting. User agent set to a plain Chrome string.

7. **Shebang:** `#!/usr/bin/env python3`. Deps: `PyQt6>=6.4.0`, `PyQt6-WebEngine>=6.4.0` in `requirements.txt`.

Deliver: `browser.py`, `claw.sh` (chmod +x), `requirements.txt`, `README.md` with install instructions and full API/CLI reference.
