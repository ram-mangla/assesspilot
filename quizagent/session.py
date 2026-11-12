"""Manual browser session for user-controlled work. Single Playwright worker thread owns Chromium.
No answering, submitting, or navigation beyond explicit HTTP endpoints."""
from __future__ import annotations

import base64
import queue
import threading
import time
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from .adapters import GenericAdapter
from .browser_ctrl import BrowserController
from .browser_launcher import find_chrome_executable


def validate_url(url: str) -> str:
    try:
        u = urlsplit((url or "").strip())
    except ValueError as e:
        raise ValueError(f"invalid URL: {e}")
    if u.scheme not in {"http", "https"} or not u.netloc:
        raise ValueError("only absolute http:// or https:// URLs are allowed")
    return f"{u.scheme}://{u.netloc}{u.path or '/'}" + (("?" + u.query) if u.query else "")


def normalize_question(q) -> dict:
    return {
        "question_id": q.key,
        "question_text": q.prompt,
        "question_type": {"select": "single_choice", "multi": "multiple_choice", "number": "short_answer"}.get(q.kind, q.kind),
        "kind": q.kind,
        "options": [{"id": (o.value or chr(65 + i)), "text": o.text, "selected": bool(o.checked)} for i, o in enumerate(q.options)],
        "images": [],
        "question_index": None,
        "total_questions": None,
        "answered": bool(q.answered),
        "mode": q.mode,
        "reliable": bool(q.reliable),
    }


class _Worker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="quizagent-browser")
        self.cmds: "queue.Queue" = queue.Queue()
        self.p = None
        self.browser = None
        self.ctx = None
        self.page = None
        self.ctrl = None
        self.ready = threading.Event()
        self.lock = threading.Lock()

    def run(self):
        with sync_playwright() as self.p:
            self.ready.set()
            while True:
                kind, arg, out = self.cmds.get()
                if kind == "_quit":
                    try:
                        if self.browser:
                            self.browser.close()
                    finally:
                        out.put(("ok", None))
                    return
                try:
                    with self.lock:
                        out.put(("ok", self._do(kind, arg)))
                except Exception as e:  # surfaced to caller; never kills the worker silently
                    out.put(("error", f"{type(e).__name__}: {e}"))

    def _do(self, kind, arg):
        if kind == "start":
            self._close()
            opts = arg or {}
            headless = not opts.get("headed", True)
            profile = opts.get("profile")
            cdp = opts.get("cdp")
            if cdp:  # attach to an already-running real Chrome (its own profile, its own login)
                self.browser = self.p.chromium.connect_over_cdp(cdp)
                ctx = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
            elif profile:  # profile copy -> persistent context keeps its cookies/login
                self.browser = None
                p_kw = {"headless": headless, "args": ["--no-sandbox"], "viewport": {"width": 1280, "height": 900}}
                chrome_exe = find_chrome_executable()
                if chrome_exe and os.path.exists(chrome_exe):
                    p_kw["executable_path"] = chrome_exe
                else:
                    try:
                        p_kw["channel"] = "chrome"
                    except Exception:
                        pass
                try:
                    ctx = self.p.chromium.launch_persistent_context(profile, **p_kw)
                except Exception:
                    p_kw.pop("executable_path", None)
                    p_kw.pop("channel", None)
                    ctx = self.p.chromium.launch_persistent_context(profile, **p_kw)
            else:
                l_kw = {"headless": headless, "args": ["--no-sandbox"]}
                chrome_exe = find_chrome_executable()
                if chrome_exe and os.path.exists(chrome_exe):
                    l_kw["executable_path"] = chrome_exe
                try:
                    self.browser = self.p.chromium.launch(**l_kw)
                except Exception:
                    self.browser = self.p.chromium.launch(headless=headless, args=["--no-sandbox"])
                ctx = self.browser.new_context(viewport={"width": 1280, "height": 900})
            self.page = (ctx.pages[0] if (cdp and ctx.pages) else None) or ctx.new_page()
            self.ctx = None if self.browser else ctx
            self.ctrl = BrowserController(self.page)
            self.ctrl.attach_dialog_handler()
            res = self._goto(opts.get("url") or "about:blank") if opts.get("url") else self._status()
            if opts.get("url"):
                try:
                    self.ctrl.wait_ready()
                except Exception:
                    pass
            return res
        if kind == "ctrl":
            op, kwargs = arg if isinstance(arg, tuple) else (arg, {})
            fn = getattr(self._controller(), op, None)
            if fn is None:
                raise ValueError(f"unknown controller operation {op}")
            return fn(**kwargs)
        if kind == "set_page":
            pages = self.page.context.pages
            if not (0 <= int(arg) < len(pages)):
                raise ValueError(f"tab {arg} does not exist")
            self.page = pages[int(arg)]
            self.ctrl = BrowserController(self.page)
            self.ctrl.attach_dialog_handler()
            self.page.bring_to_front()
            return self._status()
        page = self._page()
        if kind == "goto":
            return self._goto(arg)
        if kind == "refresh":
            page.reload(wait_until="domcontentloaded", timeout=30000)
            return self._status()
        if kind == "back":
            try:
                page.go_back(wait_until="domcontentloaded", timeout=15000)
            except Exception:
                pass
            return self._status()
        if kind == "forward":
            try:
                page.go_forward(wait_until="domcontentloaded", timeout=15000)
            except Exception:
                pass
            return self._status()
        if kind == "stop":
            self._close()
            return {"connected": False, "url": None, "title": None}
        if kind == "status":
            return self._status()
        if kind == "screenshot":
            return "data:image/jpeg;base64," + base64.b64encode(page.screenshot(type="jpeg", quality=70, full_page=False)).decode()
        if kind == "current_question":
            obs = GenericAdapter().observe(page)
            if not obs.questions:
                return {"found": False, "url": page.url, "title": page.title(), "question_count": 0, "questions": []}
            qs = [normalize_question(q) for q in obs.questions]
            return {"found": True, "url": page.url, "title": page.title(), "question_count": len(qs),
                    "question_index": 1 if len(qs) == 1 else None, "total_questions": None,
                    "current": qs[0], "questions": qs}
        raise ValueError(f"unknown command {kind}")

    def _goto(self, url):
        self.page.goto(validate_url(url), wait_until="domcontentloaded", timeout=30000)
        return self._status()

    def _controller(self):
        old = self.page
        page = self._page()
        if page is not old or not getattr(self, "ctrl", None) or self.ctrl.page is not page:
            self.ctrl = BrowserController(page)
            self.ctrl.attach_dialog_handler()
        return self.ctrl

    def _page(self):
        if not (self.browser or self.ctx) or not self.page or self.page.is_closed():
            raise RuntimeError("browser session is not running or the page was closed")
        return self.page

    def _status(self):
        if not (self.browser or self.ctx) or not self.page or self.page.is_closed():
            return {"connected": False, "url": None, "title": None}
        page = self.page
        return {"connected": True, "url": page.url, "title": page.title()}

    def _close(self):
        for obj in (self.browser, self.ctx):
            if obj:
                try:
                    obj.close()
                except Exception:
                    pass
        self.browser, self.ctx, self.page = None, None, None


class ManualBrowserSession:
    def __init__(self):
        self.worker = _Worker()
        self.worker.start()
        self.worker.ready.wait(timeout=10)

    def call(self, command: str, arg=None, timeout: float = 45.0):
        out: "queue.Queue" = queue.Queue(maxsize=1)
        self.worker.cmds.put((command, arg, out))
        try:
            kind, value = out.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"browser command {command!r} timed out after {timeout}s")
        if kind == "error":
            raise RuntimeError(value)
        return value

    def stop(self):
        try:
            self.call("_quit", timeout=10)
        except Exception:
            pass

    def ctrl(self, op: str, timeout: float = 45.0, **kwargs):
        """Run one BrowserController method on the browser thread."""
        return self.call("ctrl", (op, kwargs), timeout=timeout)

    def start(self, url: str | None = None, headed: bool = True, profile: str | None = None,
              cdp: str | None = None):
        return self.call("start", {"url": url, "headed": headed, "profile": profile, "cdp": cdp}, timeout=90)

    def select_tab(self, index: int):
        return self.call("set_page", index, timeout=20)