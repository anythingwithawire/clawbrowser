#!/usr/bin/env python3
"""
ClawBrowser — A real Chromium browser with an HTTP control API for AI agents.
No Selenium, no Playwright, no CDP. Just PyQt6 WebEngine + a localhost REST API.
"""

import sys
import os
import json
import time
import uuid
import threading
import urllib.request
import urllib.parse
import re
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QTabBar, QLineEdit, QPushButton, QToolBar,
    QStatusBar, QLabel, QMenu, QFileDialog, QMessageBox,
    QDialog, QListWidget, QListWidgetItem
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import (
    QWebEnginePage, QWebEngineProfile, QWebEngineSettings,
    QWebEngineUrlRequestInterceptor, QWebEngineDownloadRequest
)
from PyQt6.QtCore import (
    Qt, QUrl, QObject, pyqtSignal, QTimer, QBuffer, QByteArray, QPoint,
    QThread
)
from PyQt6.QtGui import (
    QKeySequence, QShortcut, QImage, QMouseEvent, QAction, QPixmap
)

# ── Paths ──────────────────────────────────────────────────────────────────
HOME = Path.home()
DATA_DIR = HOME / ".clawbrowser"
DATA_DIR.mkdir(exist_ok=True)
BOOKMARKS_FILE = DATA_DIR / "bookmarks.json"
HISTORY_FILE   = DATA_DIR / "history.json"
ADBLOCKER_FILE = DATA_DIR / "blocked_domains.txt"
WHITELIST_FILE = DATA_DIR / "whitelist.txt"
DOWNLOAD_DIR   = HOME / "Downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

API_PORT = int(os.environ.get("CLAW_PORT", 8765))

# ── Global state shared between HTTP thread and Qt thread ─────────────────
pending_results: dict[str, object] = {}   # req_id → result
pending_lock = threading.Lock()


def set_result(req_id: str, value):
    with pending_lock:
        pending_results[req_id] = value


def wait_result(req_id: str, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with pending_lock:
            if req_id in pending_results:
                return pending_results.pop(req_id)
        time.sleep(0.02)
    return {"error": "timeout"}


# ── Ad-block interceptor ───────────────────────────────────────────────────
class AdBlockInterceptor(QWebEngineUrlRequestInterceptor):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.blocked: set[str] = set()
        self.whitelist: set[str] = set()
        self.count = 0
        self._load()

    def _load(self):
        if ADBLOCKER_FILE.exists():
            domains = set()
            with open(ADBLOCKER_FILE) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        domains.add(line.lower())
            self.blocked = domains
            print(f"[AdBlock] Loaded {len(self.blocked)} blocked domains")
        else:
            self._download_hosts()

        if WHITELIST_FILE.exists():
            with open(WHITELIST_FILE) as f:
                self.whitelist = {l.strip().lower() for l in f if l.strip() and not l.startswith("#")}

    def _download_hosts(self):
        url = "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts"
        print("[AdBlock] Downloading StevenBlack hosts list…")
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = resp.read().decode("utf-8", errors="ignore")
            domains = set()
            for line in data.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[0] in ("0.0.0.0", "127.0.0.1"):
                    domain = parts[1].lower()
                    if domain not in ("0.0.0.0", "localhost", "localhost.localdomain", "broadcasthost"):
                        domains.add(domain)
            self.blocked = domains
            with open(ADBLOCKER_FILE, "w") as f:
                f.write(f"# StevenBlack hosts — {len(domains)} domains\n")
                for d in sorted(domains):
                    f.write(d + "\n")
            print(f"[AdBlock] Downloaded and saved {len(domains)} blocked domains")
        except Exception as e:
            print(f"[AdBlock] Download failed: {e}")

    def interceptRequest(self, info):
        url = info.requestUrl().host().lower()
        if not url:
            return
        # strip www.
        bare = url[4:] if url.startswith("www.") else url
        if bare in self.whitelist or url in self.whitelist:
            return
        if bare in self.blocked or url in self.blocked:
            info.block(True)
            self.count += 1


# ── Custom WebPage to handle target=_blank ─────────────────────────────────
class BrowserPage(QWebEnginePage):
    new_tab_requested = pyqtSignal(QUrl)

    def __init__(self, profile, parent=None):
        super().__init__(profile, parent)

    def createWindow(self, win_type):
        page = BrowserPage(self.profile(), self)
        page.urlChanged.connect(lambda url: self.new_tab_requested.emit(url))
        # Propagate the signal chain
        page.new_tab_requested.connect(self.new_tab_requested)
        return page


# ── Signals hub (lives on Qt main thread) ─────────────────────────────────
class BrowserSignals(QObject):
    navigate_sig    = pyqtSignal(str, str)   # req_id, url
    screenshot_sig  = pyqtSignal(str)        # req_id
    dom_sig         = pyqtSignal(str)        # req_id
    eval_sig        = pyqtSignal(str, str)   # req_id, script
    click_sel_sig   = pyqtSignal(str, str)   # req_id, selector
    click_xy_sig    = pyqtSignal(str, int, int)  # req_id, x, y
    type_sig        = pyqtSignal(str, str, str)  # req_id, selector, text
    new_tab_sig     = pyqtSignal(str, str)   # req_id, url
    close_tab_sig   = pyqtSignal(str, int)   # req_id, index (-1 = active)
    switch_tab_sig  = pyqtSignal(str, int)   # req_id, index
    add_bm_sig      = pyqtSignal(str, str, str)  # req_id, url, title
    del_bm_sig      = pyqtSignal(str, str)   # req_id, url


signals = BrowserSignals()


# ── HTTP API server ────────────────────────────────────────────────────────
class APIHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # silence default logging

    def _send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data: bytes, ctype="image/png"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _dispatch(self, signal_emit_fn) -> object:
        """Emit a signal and wait for the result."""
        req_id = str(uuid.uuid4())
        signal_emit_fn(req_id)
        return wait_result(req_id)

    # ── GET ────────────────────────────────────────────────────────────────
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/status":
            result = self._dispatch(lambda rid: signals.screenshot_sig.emit(rid))
            # We repurpose screenshot_sig to also get status — use a status-specific signal
            # Actually use a simpler approach: read global browser state
            status = _get_browser_status()
            self._send_json(status)

        elif path == "/tabs":
            tabs = _get_tabs()
            self._send_json(tabs)

        elif path == "/screenshot":
            req_id = str(uuid.uuid4())
            signals.screenshot_sig.emit(req_id)
            result = wait_result(req_id)
            if isinstance(result, bytes):
                self._send_bytes(result)
            else:
                self._send_json(result, 500)

        elif path == "/dom":
            req_id = str(uuid.uuid4())
            signals.dom_sig.emit(req_id)
            result = wait_result(req_id)
            self._send_json(result)

        elif path == "/history":
            q = qs.get("q", [""])[0]
            limit = int(qs.get("limit", [50])[0])
            history = load_history()
            if q:
                q_low = q.lower()
                history = [h for h in history if q_low in h.get("url","").lower() or q_low in h.get("title","").lower()]
            self._send_json(history[:limit])

        elif path == "/bookmarks":
            self._send_json(load_bookmarks())

        else:
            self._send_json({"error": "not found"}, 404)

    # ── POST ───────────────────────────────────────────────────────────────
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        body = self._read_body()

        if path == "/navigate":
            url = body.get("url", "")
            req_id = str(uuid.uuid4())
            signals.navigate_sig.emit(req_id, url)
            result = wait_result(req_id)
            self._send_json(result)

        elif path == "/click":
            if "selector" in body:
                req_id = str(uuid.uuid4())
                signals.click_sel_sig.emit(req_id, body["selector"])
                result = wait_result(req_id)
                self._send_json(result)
            elif "x" in body and "y" in body:
                req_id = str(uuid.uuid4())
                signals.click_xy_sig.emit(req_id, int(body["x"]), int(body["y"]))
                result = wait_result(req_id)
                self._send_json(result)
            else:
                self._send_json({"error": "need selector or x,y"}, 400)

        elif path == "/type":
            req_id = str(uuid.uuid4())
            signals.type_sig.emit(req_id, body.get("selector",""), body.get("text",""))
            result = wait_result(req_id)
            self._send_json(result)

        elif path == "/eval":
            req_id = str(uuid.uuid4())
            signals.eval_sig.emit(req_id, body.get("script",""))
            result = wait_result(req_id)
            self._send_json(result)

        elif path == "/tab/new":
            req_id = str(uuid.uuid4())
            signals.new_tab_sig.emit(req_id, body.get("url","about:blank"))
            result = wait_result(req_id)
            self._send_json(result)

        elif path == "/tab/close":
            req_id = str(uuid.uuid4())
            signals.close_tab_sig.emit(req_id, int(body.get("index", -1)))
            result = wait_result(req_id)
            self._send_json(result)

        elif path == "/tab/switch":
            req_id = str(uuid.uuid4())
            signals.switch_tab_sig.emit(req_id, int(body.get("index", 0)))
            result = wait_result(req_id)
            self._send_json(result)

        elif path == "/bookmarks":
            req_id = str(uuid.uuid4())
            signals.add_bm_sig.emit(req_id, body.get("url",""), body.get("title",""))
            result = wait_result(req_id)
            self._send_json(result)

        else:
            self._send_json({"error": "not found"}, 404)

    # ── DELETE ─────────────────────────────────────────────────────────────
    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        body = self._read_body()

        if path == "/bookmarks":
            req_id = str(uuid.uuid4())
            signals.del_bm_sig.emit(req_id, body.get("url",""))
            result = wait_result(req_id)
            self._send_json(result)
        else:
            self._send_json({"error": "not found"}, 404)


def run_api_server():
    server = HTTPServer(("127.0.0.1", API_PORT), APIHandler)
    server.serve_forever()


# ── Persistence helpers ────────────────────────────────────────────────────
def load_bookmarks() -> list:
    if BOOKMARKS_FILE.exists():
        try:
            return json.loads(BOOKMARKS_FILE.read_text())
        except Exception:
            pass
    return []


def save_bookmarks(bms: list):
    BOOKMARKS_FILE.write_text(json.dumps(bms, indent=2))


def load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            pass
    return []


def save_history(hist: list):
    HISTORY_FILE.write_text(json.dumps(hist[-5000:], indent=2))  # keep last 5k


# ── Global browser reference (set after MainWindow created) ───────────────
_browser_window = None


def _get_browser_status() -> dict:
    if _browser_window is None:
        return {}
    w = _browser_window
    view = w.current_view()
    return {
        "url": view.url().toString() if view else "",
        "title": view.title() if view else "",
        "tab_count": w.tabs.count(),
        "ads_blocked": w.interceptor.count,
    }


def _get_tabs() -> list:
    if _browser_window is None:
        return []
    w = _browser_window
    result = []
    for i in range(w.tabs.count()):
        v = w.tabs.widget(i)
        result.append({
            "index": i,
            "url": v.url().toString(),
            "title": v.title() or w.tabs.tabText(i),
            "active": i == w.tabs.currentIndex(),
        })
    return result


# ── Main Browser Window ────────────────────────────────────────────────────
class BrowserWindow(QMainWindow):
    def __init__(self, start_url="https://www.google.com", port=8765):
        super().__init__()
        self.port = port
        self.history: list = load_history()
        self.bookmarks: list = load_bookmarks()
        self._fullscreen = False

        # Shared profile and interceptor
        self.profile = QWebEngineProfile("ClawBrowser", self)
        self.profile.setHttpUserAgent(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
        )
        # Enable persistent storage
        self.profile.setPersistentStoragePath(str(DATA_DIR / "storage"))
        self.profile.setCachePath(str(DATA_DIR / "cache"))

        self.interceptor = AdBlockInterceptor()
        self.profile.setUrlRequestInterceptor(self.interceptor)

        # Download handler
        self.profile.downloadRequested.connect(self._on_download)

        self._build_ui()
        self._connect_signals()
        self._apply_shortcuts()

        self.new_tab(start_url)
        self.setWindowTitle("ClawBrowser")
        self.resize(1280, 900)

        # Status bar message
        self.statusBar().showMessage(f"API listening on http://127.0.0.1:{port}")

    # ── UI construction ────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Navigation toolbar
        nav = QToolBar("Navigation")
        nav.setMovable(False)
        self.addToolBar(nav)

        self.btn_back    = QPushButton("◀")
        self.btn_fwd     = QPushButton("▶")
        self.btn_refresh = QPushButton("↺")
        self.btn_back.setFixedWidth(32)
        self.btn_fwd.setFixedWidth(32)
        self.btn_refresh.setFixedWidth(32)

        self.url_bar = QLineEdit()
        self.url_bar.setPlaceholderText("Search or type a URL…")
        self.url_bar.returnPressed.connect(self._navigate_from_bar)

        nav.addWidget(self.btn_back)
        nav.addWidget(self.btn_fwd)
        nav.addWidget(self.btn_refresh)
        nav.addWidget(self.url_bar)

        self.btn_back.clicked.connect(lambda: self.current_view().back())
        self.btn_fwd.clicked.connect(lambda: self.current_view().forward())
        self.btn_refresh.clicked.connect(lambda: self.current_view().reload())

        # Bookmarks bar
        self.bm_bar = QToolBar("Bookmarks")
        self.bm_bar.setMovable(False)
        self.addToolBar(self.bm_bar)
        self._refresh_bookmarks_bar()

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

        self.setStatusBar(QStatusBar())

    def _connect_signals(self):
        signals.navigate_sig.connect(self._handle_navigate)
        signals.screenshot_sig.connect(self._handle_screenshot)
        signals.dom_sig.connect(self._handle_dom)
        signals.eval_sig.connect(self._handle_eval)
        signals.click_sel_sig.connect(self._handle_click_sel)
        signals.click_xy_sig.connect(self._handle_click_xy)
        signals.type_sig.connect(self._handle_type)
        signals.new_tab_sig.connect(self._handle_new_tab)
        signals.close_tab_sig.connect(self._handle_close_tab)
        signals.switch_tab_sig.connect(self._handle_switch_tab)
        signals.add_bm_sig.connect(self._handle_add_bm)
        signals.del_bm_sig.connect(self._handle_del_bm)

    def _apply_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+T"), self).activated.connect(lambda: self.new_tab())
        QShortcut(QKeySequence("Ctrl+W"), self).activated.connect(lambda: self.close_tab(self.tabs.currentIndex()))
        QShortcut(QKeySequence("Ctrl+Tab"), self).activated.connect(self._next_tab)
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self).activated.connect(self._prev_tab)
        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(lambda: self.url_bar.setFocus())
        QShortcut(QKeySequence("Ctrl+D"), self).activated.connect(self._bookmark_current)
        QShortcut(QKeySequence("Ctrl+H"), self).activated.connect(self._show_history)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self._find_in_page)
        QShortcut(QKeySequence("F11"), self).activated.connect(self._toggle_fullscreen)
        QShortcut(QKeySequence("F5"), self).activated.connect(lambda: self.current_view().reload())
        QShortcut(QKeySequence("Alt+Left"), self).activated.connect(lambda: self.current_view().back())
        QShortcut(QKeySequence("Alt+Right"), self).activated.connect(lambda: self.current_view().forward())

    # ── Tab management ─────────────────────────────────────────────────────
    def new_tab(self, url: str = "about:blank") -> QWebEngineView:
        view = QWebEngineView()
        page = BrowserPage(self.profile, view)
        view.setPage(page)

        # Enable settings
        settings = page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)

        # Signals
        page.new_tab_requested.connect(lambda u: self.new_tab(u.toString()))
        view.urlChanged.connect(lambda u: self._on_url_changed(u, view))
        view.titleChanged.connect(lambda t: self._on_title_changed(t, view))
        view.loadFinished.connect(lambda ok: self._on_load_finished(ok, view))

        # Middle-click closes tab
        view.setMouseTracking(True)

        idx = self.tabs.addTab(view, "New Tab")
        self.tabs.setCurrentIndex(idx)

        if url and url != "about:blank":
            view.load(QUrl(self._smart_url(url)))
        return view

    def close_tab(self, index: int):
        if self.tabs.count() <= 1:
            return  # don't close last tab
        widget = self.tabs.widget(index)
        self.tabs.removeTab(index)
        widget.deleteLater()

    def current_view(self) -> QWebEngineView | None:
        return self.tabs.currentWidget()

    def _next_tab(self):
        n = self.tabs.count()
        self.tabs.setCurrentIndex((self.tabs.currentIndex() + 1) % n)

    def _prev_tab(self):
        n = self.tabs.count()
        self.tabs.setCurrentIndex((self.tabs.currentIndex() - 1) % n)

    # ── Navigation ─────────────────────────────────────────────────────────
    def _smart_url(self, text: str) -> str:
        text = text.strip()
        if text.startswith(("http://", "https://", "file://", "about:")):
            return text
        # Has a dot and no spaces → likely a URL
        if "." in text and " " not in text:
            return "https://" + text
        # Bare word → Google search
        return "https://www.google.com/search?q=" + urllib.parse.quote_plus(text)

    def _navigate_from_bar(self):
        view = self.current_view()
        if view:
            view.load(QUrl(self._smart_url(self.url_bar.text())))

    def navigate(self, url: str):
        view = self.current_view()
        if view:
            view.load(QUrl(self._smart_url(url)))

    # ── Tab event handlers ─────────────────────────────────────────────────
    def _on_tab_changed(self, index: int):
        view = self.tabs.widget(index)
        if view:
            self.url_bar.setText(view.url().toString())
            self.setWindowTitle(f"{view.title()} — ClawBrowser")

    def _on_url_changed(self, url: QUrl, view: QWebEngineView):
        if view == self.current_view():
            self.url_bar.setText(url.toString())

    def _on_title_changed(self, title: str, view: QWebEngineView):
        idx = self.tabs.indexOf(view)
        if idx >= 0:
            short = (title[:20] + "…") if len(title) > 20 else title
            self.tabs.setTabText(idx, short or "Loading…")
        if view == self.current_view():
            self.setWindowTitle(f"{title} — ClawBrowser")

    def _on_load_finished(self, ok: bool, view: QWebEngineView):
        url = view.url().toString()
        title = view.title()
        if url and url not in ("about:blank", ""):
            entry = {"url": url, "title": title, "ts": int(time.time())}
            self.history.insert(0, entry)
            save_history(self.history)

    # ── Bookmarks ──────────────────────────────────────────────────────────
    def _bookmark_current(self):
        view = self.current_view()
        if not view:
            return
        url = view.url().toString()
        title = view.title()
        self._add_bookmark(url, title)

    def _add_bookmark(self, url: str, title: str):
        # No dupes
        if any(b["url"] == url for b in self.bookmarks):
            return
        self.bookmarks.append({"url": url, "title": title})
        save_bookmarks(self.bookmarks)
        self._refresh_bookmarks_bar()

    def _remove_bookmark(self, url: str):
        self.bookmarks = [b for b in self.bookmarks if b["url"] != url]
        save_bookmarks(self.bookmarks)
        self._refresh_bookmarks_bar()

    def _refresh_bookmarks_bar(self):
        self.bm_bar.clear()
        for bm in self.bookmarks:
            title = bm.get("title","") or bm["url"]
            short = (title[:20] + "…") if len(title) > 20 else title
            btn = QPushButton(short)
            btn.setToolTip(bm["url"])
            url = bm["url"]

            def make_nav(u):
                return lambda: self.navigate(u)

            btn.clicked.connect(make_nav(url))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

            def make_ctx(u):
                def ctx_menu(pos):
                    menu = QMenu()
                    act = menu.addAction(f"Remove bookmark")
                    act.triggered.connect(lambda: self._remove_bookmark(u))
                    menu.exec(btn.mapToGlobal(pos))
                return ctx_menu

            btn.customContextMenuRequested.connect(make_ctx(url))
            self.bm_bar.addWidget(btn)

    # ── History viewer ─────────────────────────────────────────────────────
    def _show_history(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("History")
        dlg.resize(600, 400)
        layout = QVBoxLayout(dlg)
        lst = QListWidget()
        for entry in self.history[:200]:
            item = QListWidgetItem(f"{entry.get('title','')} — {entry['url']}")
            item.setData(Qt.ItemDataRole.UserRole, entry["url"])
            lst.addItem(item)
        lst.itemDoubleClicked.connect(lambda item: (
            self.navigate(item.data(Qt.ItemDataRole.UserRole)),
            dlg.close()
        ))
        layout.addWidget(lst)
        dlg.exec()

    # ── Find in page ───────────────────────────────────────────────────────
    def _find_in_page(self):
        text, ok = __import__("PyQt6.QtWidgets", fromlist=["QInputDialog"]).QInputDialog.getText(
            self, "Find in Page", "Search:"
        )
        if ok and text:
            view = self.current_view()
            if view:
                view.findText(text)

    # ── Downloads ──────────────────────────────────────────────────────────
    def _on_download(self, item: QWebEngineDownloadRequest):
        path = str(DOWNLOAD_DIR / item.suggestedFileName())
        item.setDownloadDirectory(str(DOWNLOAD_DIR))
        item.setDownloadFileName(item.suggestedFileName())
        item.accept()
        self.statusBar().showMessage(f"Downloading: {item.suggestedFileName()}")

    # ── Fullscreen ─────────────────────────────────────────────────────────
    def _toggle_fullscreen(self):
        if self._fullscreen:
            self.showNormal()
        else:
            self.showFullScreen()
        self._fullscreen = not self._fullscreen

    # ── Signal handlers (Qt main thread) ──────────────────────────────────
    def _handle_navigate(self, req_id: str, url: str):
        self.navigate(url)
        set_result(req_id, {"ok": True, "url": self._smart_url(url)})

    def _handle_screenshot(self, req_id: str):
        view = self.current_view()
        if not view:
            set_result(req_id, {"error": "no view"})
            return
        pixmap = view.grab()
        buf = QByteArray()
        qbuf = QBuffer(buf)
        qbuf.open(QBuffer.OpenModeFlag.WriteOnly)
        pixmap.save(qbuf, "PNG")
        qbuf.close()
        set_result(req_id, bytes(buf))

    def _handle_dom(self, req_id: str):
        view = self.current_view()
        if not view:
            set_result(req_id, {"error": "no view"})
            return
        def cb(html):
            set_result(req_id, {"html": html})
        view.page().toHtml(cb)

    def _handle_eval(self, req_id: str, script: str):
        view = self.current_view()
        if not view:
            set_result(req_id, {"error": "no view"})
            return
        def cb(result):
            set_result(req_id, {"result": result})
        view.page().runJavaScript(script, cb)

    def _handle_click_sel(self, req_id: str, selector: str):
        view = self.current_view()
        if not view:
            set_result(req_id, {"error": "no view"})
            return
        js = f"""
        (function() {{
            var el = document.querySelector({json.dumps(selector)});
            if (!el) return 'not found';
            el.click();
            return 'clicked';
        }})()
        """
        def cb(result):
            set_result(req_id, {"result": result})
        view.page().runJavaScript(js, cb)

    def _handle_click_xy(self, req_id: str, x: int, y: int):
        view = self.current_view()
        if not view:
            set_result(req_id, {"error": "no view"})
            return
        target = view.focusProxy() or view
        pos = QPoint(x, y)
        press = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress, pos,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        release = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease, pos,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        QApplication.sendEvent(target, press)
        QApplication.sendEvent(target, release)
        set_result(req_id, {"ok": True, "x": x, "y": y})

    def _handle_type(self, req_id: str, selector: str, text: str):
        view = self.current_view()
        if not view:
            set_result(req_id, {"error": "no view"})
            return
        safe_text = json.dumps(text)
        safe_sel  = json.dumps(selector)
        js = f"""
        (function() {{
            var el = document.querySelector({safe_sel});
            if (!el) return 'not found';
            el.focus();
            el.value = {safe_text};
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            return 'typed';
        }})()
        """
        def cb(result):
            set_result(req_id, {"result": result})
        view.page().runJavaScript(js, cb)

    def _handle_new_tab(self, req_id: str, url: str):
        self.new_tab(url)
        set_result(req_id, {"ok": True, "index": self.tabs.currentIndex()})

    def _handle_close_tab(self, req_id: str, index: int):
        idx = index if index >= 0 else self.tabs.currentIndex()
        self.close_tab(idx)
        set_result(req_id, {"ok": True})

    def _handle_switch_tab(self, req_id: str, index: int):
        if 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)
            set_result(req_id, {"ok": True})
        else:
            set_result(req_id, {"error": f"invalid index {index}"})

    def _handle_add_bm(self, req_id: str, url: str, title: str):
        self._add_bookmark(url, title)
        set_result(req_id, {"ok": True})

    def _handle_del_bm(self, req_id: str, url: str):
        self._remove_bookmark(url)
        set_result(req_id, {"ok": True})


# ── Entry point ────────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="ClawBrowser")
    parser.add_argument("--port", type=int, default=API_PORT, help="API port (default 8765)")
    parser.add_argument("--url", default="https://www.google.com", help="Start URL")
    args = parser.parse_args()

    # Start API server in background thread
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()
    print(f"[ClawBrowser] API server started on http://127.0.0.1:{args.port}")

    app = QApplication(sys.argv)
    app.setApplicationName("ClawBrowser")
    app.setOrganizationName("Claw")

    global _browser_window
    _browser_window = BrowserWindow(start_url=args.url, port=args.port)
    _browser_window.show()

    print(f"[ClawBrowser] Browser window open — use claw.sh to control it")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
