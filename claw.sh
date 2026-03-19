#!/usr/bin/env bash
# claw.sh — ClawBrowser CLI wrapper
# Control the ClawBrowser HTTP API with simple commands.
# Set CLAW_PORT env var to change port (default: 8765)

PORT="${CLAW_PORT:-8765}"
BASE="http://127.0.0.1:${PORT}"

usage() {
    cat <<EOF
Launch: python3 browser.py [--port 8765] [--url URL] [--virtual WxH]
  --virtual WxH  Run on a private Xvfb display (e.g. --virtual 1920x1080)

Usage: claw.sh <command> [args]

Commands:
  status              Browser status + ads blocked count
  go <url>            Navigate to URL
  shot [file]         Screenshot to file (default: /tmp/claw_shot.png)
  dom [chars]         Page HTML (truncated to chars, default 5000)
  text [chars]        Visible text only (document.body.innerText)
  click <selector>    Click by CSS selector
  click <x>,<y>       Click by coordinates (e.g. claw.sh click 100,200)
  type <sel> <text>   Type text into input element
  js <script>         Run JavaScript and print result
  links               List all links on the page
  forms               List all form inputs on the page
  tabs                List all open tabs
  tab new [url]       Open a new tab
  tab close [index]   Close a tab (default: active)
  tab switch <index>  Switch to tab by index
  bookmarks           List bookmarks
  bookmark add <url> [title]  Add a bookmark
  bookmark del <url>  Remove a bookmark
  history [query]     Search browsing history
  resize <W> <H>      Resize browser window (e.g. claw.sh resize 1920 1080)
  zoom <factor>       Set page zoom factor (e.g. claw.sh zoom 1.5 for 150%)
  wait [secs]         Wait N seconds (default 2) then show status
EOF
    exit 1
}

# Check browser is running
check_running() {
    if ! curl -sf "${BASE}/status" > /dev/null 2>&1; then
        echo "ERROR: ClawBrowser not running on port ${PORT}" >&2
        echo "Start it with: python ~/tools/clawbrowser/browser.py" >&2
        exit 1
    fi
}

cmd="${1:-}"
shift || true

case "$cmd" in
    status)
        check_running
        curl -sf "${BASE}/status" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f\"URL:          {d.get('url','')}\")
print(f\"Title:        {d.get('title','')}\")
print(f\"Tabs:         {d.get('tab_count','')}\")
print(f\"Ads blocked:  {d.get('ads_blocked','')}\")
"
        ;;

    go)
        url="${1:-}"
        if [[ -z "$url" ]]; then echo "Usage: claw.sh go <url>"; exit 1; fi
        check_running
        curl -sf -X POST "${BASE}/navigate" \
            -H "Content-Type: application/json" \
            -d "{\"url\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$url")}"
        echo ""
        ;;

    shot|screenshot)
        file="${1:-/tmp/claw_shot.png}"
        check_running
        curl -sf "${BASE}/screenshot" -o "$file"
        echo "Screenshot saved to: $file"
        ;;

    dom)
        chars="${1:-5000}"
        check_running
        curl -sf "${BASE}/dom" | python3 -c "
import json, sys
d = json.load(sys.stdin)
html = d.get('html', '')
limit = int(sys.argv[1])
print(html[:limit])
if len(html) > limit:
    print(f'... [{len(html)-limit} chars truncated]')
" "$chars"
        ;;

    text)
        chars="${1:-5000}"
        check_running
        SCRIPT="document.body ? document.body.innerText : ''"
        result=$(curl -sf -X POST "${BASE}/eval" \
            -H "Content-Type: application/json" \
            -d "{\"script\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$SCRIPT")}")
        echo "$result" | python3 -c "
import json, sys
d = json.load(sys.stdin)
text = d.get('result', '') or ''
limit = int(sys.argv[1])
print(text[:limit])
if len(text) > limit:
    print(f'... [{len(text)-limit} chars truncated]')
" "$chars"
        ;;

    click)
        target="${1:-}"
        if [[ -z "$target" ]]; then echo "Usage: claw.sh click <selector> or <x,y>"; exit 1; fi
        check_running
        if [[ "$target" =~ ^[0-9]+,[0-9]+$ ]]; then
            x="${target%%,*}"
            y="${target##*,}"
            curl -sf -X POST "${BASE}/click" \
                -H "Content-Type: application/json" \
                -d "{\"x\": $x, \"y\": $y}"
        else
            curl -sf -X POST "${BASE}/click" \
                -H "Content-Type: application/json" \
                -d "{\"selector\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$target")}"
        fi
        echo ""
        ;;

    type)
        selector="${1:-}"
        text="${2:-}"
        if [[ -z "$selector" || -z "$text" ]]; then
            echo "Usage: claw.sh type <selector> <text>"
            exit 1
        fi
        check_running
        curl -sf -X POST "${BASE}/type" \
            -H "Content-Type: application/json" \
            -d "{\"selector\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$selector"), \"text\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$text")}"
        echo ""
        ;;

    js|eval)
        script="${1:-}"
        if [[ -z "$script" ]]; then echo "Usage: claw.sh js <script>"; exit 1; fi
        check_running
        result=$(curl -sf -X POST "${BASE}/eval" \
            -H "Content-Type: application/json" \
            -d "{\"script\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$script")}")
        echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('result',''))"
        ;;

    links)
        check_running
        SCRIPT="JSON.stringify(Array.from(document.querySelectorAll('a[href]')).map(a => ({text: a.textContent.trim().slice(0,80), href: a.href})))"
        result=$(curl -sf -X POST "${BASE}/eval" \
            -H "Content-Type: application/json" \
            -d "{\"script\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$SCRIPT")}")
        echo "$result" | python3 -c "
import json, sys
d = json.load(sys.stdin)
links = json.loads(d.get('result', '[]') or '[]')
for i, link in enumerate(links):
    print(f\"[{i}] {link['text']:<50} {link['href']}\")
print(f'--- {len(links)} links ---')
"
        ;;

    forms)
        check_running
        SCRIPT="JSON.stringify(Array.from(document.querySelectorAll('input,textarea,select,button')).map(el => ({tag: el.tagName.toLowerCase(), type: el.type||'', name: el.name||'', id: el.id||'', placeholder: el.placeholder||'', value: el.value||''}).slice ? undefined : ({tag: el.tagName.toLowerCase(), type: el.type||'', name: el.name||'', id: el.id||'', placeholder: el.placeholder||'', value: el.value||''})).filter(Boolean))"
        SCRIPT2="JSON.stringify(Array.from(document.querySelectorAll('input,textarea,select,button')).map(el => ({tag: el.tagName.toLowerCase(), type: el.getAttribute('type')||'', name: el.name||'', id: el.id||'', placeholder: el.placeholder||'', value: el.value||''})))"
        result=$(curl -sf -X POST "${BASE}/eval" \
            -H "Content-Type: application/json" \
            -d "{\"script\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$SCRIPT2")}")
        echo "$result" | python3 -c "
import json, sys
d = json.load(sys.stdin)
items = json.loads(d.get('result', '[]') or '[]')
for i, el in enumerate(items):
    desc = f\"[{i}] <{el['tag']}\"
    if el['type']: desc += f\" type={el['type']}\"
    if el['name']: desc += f\" name={el['name']}\"
    if el['id']:   desc += f\" id={el['id']}\"
    if el['placeholder']: desc += f\" placeholder=\\\"{el['placeholder']}\\\"\"
    if el['value']: desc += f\" value=\\\"{el['value'][:30]}\\\"\"
    desc += '>'
    print(desc)
print(f'--- {len(items)} form elements ---')
"
        ;;

    tabs)
        check_running
        curl -sf "${BASE}/tabs" | python3 -c "
import json, sys
tabs = json.load(sys.stdin)
for t in tabs:
    active = ' ◀ ACTIVE' if t.get('active') else ''
    print(f\"[{t['index']}] {t.get('title',''):<40} {t.get('url','')}{active}\")
"
        ;;

    tab)
        subcmd="${1:-}"
        shift || true
        check_running
        case "$subcmd" in
            new)
                url="${1:-about:blank}"
                curl -sf -X POST "${BASE}/tab/new" \
                    -H "Content-Type: application/json" \
                    -d "{\"url\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$url")}"
                echo ""
                ;;
            close)
                idx="${1:--1}"
                curl -sf -X POST "${BASE}/tab/close" \
                    -H "Content-Type: application/json" \
                    -d "{\"index\": $idx}"
                echo ""
                ;;
            switch)
                idx="${1:-0}"
                curl -sf -X POST "${BASE}/tab/switch" \
                    -H "Content-Type: application/json" \
                    -d "{\"index\": $idx}"
                echo ""
                ;;
            *)
                echo "Usage: claw.sh tab new|close|switch [args]"
                ;;
        esac
        ;;

    bookmarks)
        check_running
        curl -sf "${BASE}/bookmarks" | python3 -c "
import json, sys
bms = json.load(sys.stdin)
for b in bms:
    print(f\"{b.get('title',''):<50} {b.get('url','')}\")
print(f'--- {len(bms)} bookmarks ---')
"
        ;;

    bookmark)
        subcmd="${1:-}"
        shift || true
        check_running
        case "$subcmd" in
            add)
                url="${1:-}"
                title="${2:-}"
                if [[ -z "$url" ]]; then echo "Usage: claw.sh bookmark add <url> [title]"; exit 1; fi
                curl -sf -X POST "${BASE}/bookmarks" \
                    -H "Content-Type: application/json" \
                    -d "{\"url\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$url"), \"title\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$title")}"
                echo ""
                ;;
            del|delete|remove)
                url="${1:-}"
                if [[ -z "$url" ]]; then echo "Usage: claw.sh bookmark del <url>"; exit 1; fi
                curl -sf -X DELETE "${BASE}/bookmarks" \
                    -H "Content-Type: application/json" \
                    -d "{\"url\": $(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$url")}"
                echo ""
                ;;
            *)
                echo "Usage: claw.sh bookmark add|del [args]"
                ;;
        esac
        ;;

    history)
        query="${1:-}"
        check_running
        url="${BASE}/history"
        if [[ -n "$query" ]]; then
            url="${url}?q=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote_plus(sys.argv[1]))" "$query")&limit=50"
        else
            url="${url}?limit=50"
        fi
        curl -sf "$url" | python3 -c "
import json, sys, datetime
entries = json.load(sys.stdin)
for e in entries:
    ts = e.get('ts', 0)
    dt = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M') if ts else '?'
    print(f\"{dt}  {e.get('title',''):<50}  {e.get('url','')}\")
print(f'--- {len(entries)} entries ---')
"
        ;;

    resize)
        w="${1:-}"
        h="${2:-}"
        if [[ -z "$w" || -z "$h" ]]; then echo "Usage: claw.sh resize <width> <height>"; exit 1; fi
        check_running
        curl -sf -X POST "${BASE}/resize" \
            -H "Content-Type: application/json" \
            -d "{\"width\": $w, \"height\": $h}"
        echo ""
        ;;

    zoom)
        factor="${1:-}"
        if [[ -z "$factor" ]]; then echo "Usage: claw.sh zoom <factor>  (e.g. 1.0, 1.5, 2.0)"; exit 1; fi
        check_running
        curl -sf -X POST "${BASE}/zoom" \
            -H "Content-Type: application/json" \
            -d "{\"factor\": $factor}"
        echo ""
        ;;

    wait)
        secs="${1:-2}"
        echo "Waiting ${secs}s…"
        sleep "$secs"
        check_running
        "$0" status
        ;;

    ""|help|--help|-h)
        usage
        ;;

    *)
        echo "Unknown command: $cmd"
        usage
        ;;
esac
