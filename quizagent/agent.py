import json
import random
import re
import time
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import adapters as A
from .browser_launcher import find_chrome_executable
from .learner import SelfLearningEngine
from .model import Choice, Obs
from .normalize import norm
from .scanjs import SETTLE_JS, STATE_JS
from .strategies import NoAnswer

SCORE_RX = re.compile(r"(\d+(?:\.\d+)?)\s*(?:/|out of)\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*%", re.I)
TEXT_KINDS = ("text", "textarea", "number")
SKIPPED = Choice(source="skip", matched=False)


class Agent:
    def __init__(self, strategy, behavior, cache, seed=0, out_dir="runs", max_steps=150, headed=False,
                 creds=None, adapter="auto", config=None, trace=False, use_state=True, chrome_path=None,
                 cdp=None, profile=None, storage_state=None, confirm_submit=False, learner=None):
        self.strategy, self.beh, self.cache = strategy, behavior, cache
        self.rng = random.Random(seed)
        self.out = Path(out_dir)
        self.max_steps, self.headed, self.creds = max_steps, headed, creds
        self.adapter_name, self.config, self.trace, self.use_state = adapter, config, trace, use_state
        self.chrome_path = chrome_path or find_chrome_executable()
        self.cdp, self.profile = cdp, profile
        self.storage_state = storage_state
        self.confirm_submit = confirm_submit
        cache_dir = str(cache.root) if (cache and getattr(cache, "enabled", False)) else ".quizagent_cache"
        self.learner = learner or SelfLearningEngine(cache_dir)
        self.on_event = None      # callable(kind, data): 'step' | 'shot' | 'status'
        self.stop = None          # threading.Event
        self._last = None
        self.dialogs: list[str] = []

    # ------------------------------------------------------------------ browser
    def _launch(self, p):
        kw = {"headless": not self.headed, "args": ["--no-sandbox"]}
        if self.chrome_path and Path(self.chrome_path).exists():
            kw["executable_path"] = self.chrome_path
            try:
                return p.chromium.launch(**kw)
            except Exception:
                pass
        try:                                   # any OS: Playwright locates an installed Google Chrome
            return p.chromium.launch(channel="chrome", **kw)
        except Exception:
            return p.chromium.launch(**kw)     # bundled Chromium (setup scripts install it if Chrome is absent)

    @contextmanager
    def session(self, url):
        """Yield (ctx, page, url). Modes: own browser | persistent --profile | attach to running Chrome via --cdp.
        url == 'here' (cdp only) = operate on the tab currently visible in that browser."""
        with sync_playwright() as p:
            if self.cdp:
                browser = p.chromium.connect_over_cdp(self.cdp)
                ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                page, created = None, False
                if url == "here":
                    for pg in ctx.pages:
                        try:
                            if pg.evaluate("document.visibilityState") == "visible" and not pg.url.startswith(("chrome:", "devtools:")):
                                page = pg
                                break
                        except Exception:
                            continue
                    if page is None:
                        raise RuntimeError("no visible tab found in the attached browser")
                    url = page.url
                else:
                    norm = lambda u: u.split("#")[0].split("?")[0].rstrip("/").lower()
                    target_norm = norm(url)
                    for pg in ctx.pages:
                        try:
                            if norm(pg.url) == target_norm:
                                page = pg
                                break
                        except Exception:
                            continue
                    if page is not None:
                        try:
                            page.bring_to_front()
                        except Exception:
                            pass
                    else:
                        page, created = ctx.new_page(), True
                page.on("dialog", self._dialog)
                try:
                    yield ctx, page, url
                finally:
                    if created:
                        try:
                            page.close()
                        except Exception:
                            pass
                return                               # never close the user's browser
            if self.profile:
                from .browser_launcher import resolve_chrome_profile
                prof_path = resolve_chrome_profile(self.profile) or self.profile
                kw = {"headless": not self.headed, "args": ["--no-sandbox"], "viewport": {"width": 1280, "height": 900}}
                if self.chrome_path and Path(self.chrome_path).exists():
                    kw["executable_path"] = self.chrome_path
                else:
                    try:
                        kw["channel"] = "chrome"
                    except Exception:
                        pass

                state_file = Path(prof_path) / "qa_storage_state.json"
                if state_file.exists():
                    try:
                        kw["storage_state"] = str(state_file)
                    except Exception:
                        pass

                ctx = p.chromium.launch_persistent_context(prof_path, **kw)
                # Chrome discards session cookies (Moodle, Google OAuth, etc.) when a profile closes: persist them ourselves
                sf = Path(prof_path) / "qa_cookies.json"
                if sf.exists():
                    try:
                        ctx.add_cookies(json.loads(sf.read_text()))
                    except Exception:
                        pass
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.on("dialog", self._dialog)
                try:
                    yield ctx, page, url
                finally:
                    try:
                        sf.write_text(json.dumps(ctx.cookies()))
                        sf.chmod(0o600)
                        ctx.storage_state(path=str(state_file))
                        state_file.chmod(0o600)
                    except Exception:
                        pass
                    ctx.close()
                return
            browser = self._launch(p)
            ctx, page = self._context(browser, url)
            try:
                yield ctx, page, url
            finally:
                browser.close()

    def _dialog(self, d):
        self.dialogs.append(f"{d.type}: {d.message}")
        try:
            d.accept()
        except Exception:
            pass

    def settle(self, page):
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=1500)
        except Exception:
            pass
        for _ in range(3):
            try:
                page.evaluate(SETTLE_JS)
                return
            except Exception:
                time.sleep(0.25)

    # ------------------------------------------------------------------ entry
    def probe(self, url):
        """Dry run: detect adapter, list what the scanner sees. Performs no actions."""
        with self.session(url) as (ctx, page, url):
            norm = lambda u: (u or "").split("#")[0].split("?")[0].rstrip("/").lower()
            if self.cdp is None or norm(page.url) != norm(url):
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            self.settle(page)
            ad = A.detect(page, None, self.adapter_name, self.config)
            obs = ad.observe(page)
            res = {"adapter": ad.name, "url": obs.url, "login": obs.login,
                   "questions": [{"kind": q.kind, "mode": q.mode, "prompt": q.prompt, "fp": q.fp, "answered": q.answered,
                                  "options": [o.text for o in q.options]} for q in obs.questions],
                   "navs": [{"text": n.text, "action": n.action, "disabled": n.disabled, "modal": n.modal} for n in obs.navs if n.action]}
            return res

    def _context(self, browser, url):
        kw = {"viewport": {"width": 1280, "height": 900}}
        if self.storage_state and Path(self.storage_state).exists():
            kw["storage_state"] = str(self.storage_state)
        else:
            sp = self.cache.state_path(url) if self.cache else None
            if self.use_state and sp and sp.exists():
                kw["storage_state"] = str(sp)
        ctx = browser.new_context(**kw)
        page = ctx.new_page()
        page.on("dialog", self._dialog)
        return ctx, page

    def run(self, url) -> dict:
        with self.session(url) as (ctx, page, url):
            norm = lambda u: (u or "").split("#")[0].split("?")[0].rstrip("/").lower()
            rep = self.attempt(page, ctx, url, goto=not (self.cdp and norm(page.url) == norm(url)))
        return rep

    def attempt(self, page, ctx, url, goto=True, title=None) -> dict:
        """Run one quiz attempt in an already-open browser page."""
        t0 = time.time()
        self.out.mkdir(parents=True, exist_ok=True)
        report = {"url": url, "title": title, "behavior": self.beh.name, "steps": [], "answers": [], "status": "running", "warnings": []}
        self.answers = {}
        self.dialogs = []
        try:
            if goto:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                self.settle(page)
            ad = A.detect(page, self.cache, self.adapter_name, self.config, learner=self.learner)
            report["adapter"] = ad.name
            self.loop(page, ctx, ad, report, url)
            if report["status"] == "completed" and hasattr(ad, "collect_result"):
                extra = ad.collect_result(page, url)
                if extra:
                    report["final_text_full"] = extra
            if report["status"] == "completed" and self.cache:
                self.cache.put_adapter(url, ad.name.split(":")[0])
        except NoAnswer as e:
            report["status"] = f"failed: {e}"
        except Exception as e:  # noqa
            report["status"] = f"error: {type(e).__name__}: {e}"
        if not report["status"].startswith(("completed", "running")):
            try:
                page.screenshot(path=str(self.out / f"fail-{int(t0)}.png"))
            except Exception:
                pass
        if report["status"] == "running":
            report["status"] = "failed: max_steps"
        report["answers"] = list(self.answers.values())
        report["dialogs"] = self.dialogs
        report["elapsed_s"] = round(time.time() - t0, 2)
        from .report import summarize
        report["summary"] = summarize(report)
        report.pop("final_text_full", None)
        path = self.out / f"run-{int(t0 * 1000)}.json"
        path.write_text(json.dumps(report, indent=1))
        report["report_path"] = str(path)
        if self.cache:
            self.cache.log_run(url, report.get("adapter"), self.beh.name, report["status"], len(report["steps"]), str(path))
        return report

    def auto(self, start_url, pick=None, run_all=False, list_only=False, budget=25, again=False) -> dict:
        """Autopilot: log in, discover quizzes from start_url, attempt them."""
        from .discover import Discoverer
        out = {"start": start_url, "found": [], "runs": []}
        with self.session(start_url) as (ctx, page, start_url):
            out["start"] = start_url
            d = Discoverer(self, page, ctx)
            found = d.find(start_url, budget=budget, stop_at_first=not (run_all or list_only or pick))
            out["found"] = [{"title": f.title, "url": f.url} for f in found]
            out["log"] = d.log
            targets = [f for f in found if not pick or re.search(pick, f"{f.title} {f.page_title} {f.url}", re.I)]
            if self.cache and not again:
                done = self.cache.completed_urls()
                skipped = [f.url for f in targets if f.url in done]
                targets = [f for f in targets if f.url not in done]
                out["skipped_already_completed"] = skipped
            if not run_all:
                targets = targets[:1]
            if not list_only:
                for f in targets:
                    rep = self.attempt(page, ctx, f.url, title=f.title)
                    out["runs"].append({"title": f.title, "url": f.url, "status": rep["status"], "report": rep["report_path"],
                                        "answers": len(rep["answers"]), "warnings": rep["warnings"]})
        return out

    # ------------------------------------------------------------------ main loop
    def _emit(self, kind, data):
        if self.on_event:
            try:
                self.on_event(kind, data)
            except Exception:
                pass

    def loop(self, page, ctx, ad, report, url):
        self._last = None
        try:
            self._loop(page, ctx, ad, report, url)
        finally:
            if self._last:
                self._emit("step", self._last)

    def _click_nav(self, ctx, loc, page, ad):
        old_pages = list(ctx.pages) if ctx else []
        try:
            self.click(loc)
        except Exception as e:
            logger.warning("Navigation click failed: %s", e)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        self.settle(page)
        if ctx:
            time.sleep(0.5)
            new_pages = [p for p in ctx.pages if p not in old_pages and not p.is_closed()]
            if new_pages:
                new_pg = new_pages[-1]
                try:
                    new_pg.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                new_pg.on("dialog", self._dialog)
                try:
                    new_pg.bring_to_front()
                except Exception:
                    pass
                self._page = new_pg
                self.settle(new_pg)
                new_ad = A.detect(new_pg, self.cache, self.adapter_name, self.config, learner=self.learner)
                print(f" [AssessPilot] 🔀 Switched to newly opened assessment tab: {new_pg.url} ({new_pg.title()})")
                return new_pg, new_ad
        return page, ad

    def _loop(self, page, ctx, ad, report, url):
        self._page, self._ad = page, ad
        applied: dict[str, Choice] = {}
        pending = False       # a submit/finish click has happened
        stuck = unknown = done_votes = 0
        last_sig = None
        revisit = False
        beh, rng = self.beh, self.rng

        # Check if an assessment child tab was already opened in this browser context
        if ctx and len(ctx.pages) > 1:
            for p in ctx.pages:
                if not p.is_closed() and p != page:
                    p_url = p.url.lower()
                    if any(k in p_url for k in ("onlinetests.app", "assess.aspx", "takequiz", "testengine")):
                        print(f" [AssessPilot] 🎯 Attached to active assessment tab: {p.url} ({p.title()})")
                        page = p
                        page.on("dialog", self._dialog)
                        try:
                            page.bring_to_front()
                        except Exception:
                            pass
                        self._page = page
                        self.settle(page)
                        ad = A.detect(page, self.cache, self.adapter_name, self.config, learner=self.learner)
                        break

        for n in range(self.max_steps):
            if self.stop is not None and self.stop.is_set():
                report["status"] = "stopped"
                return
            if self._last:
                self._emit("step", self._last)
            obs = ad.observe(page)
            if obs.questions:
                self.learner.learn_dom_structure(obs.url, obs.questions)
            phase = self.phase(obs, pending)
            rec = {"n": n, "phase": phase, "url": obs.url, "t": round(time.time(), 2)}
            report["steps"].append(rec)
            self._last = rec
            if self.on_event:
                try:
                    import base64
                    self._emit("shot", base64.b64encode(page.screenshot(type="jpeg", quality=55)).decode())
                except Exception:
                    pass
            if self.trace:
                page.screenshot(path=str(self.out / f"step-{n:03d}-{phase}.png"))

            if phase == "done?":
                done_votes += 1
                if done_votes >= 2:
                    phase = "done"
                else:
                    time.sleep(0.8); self.settle(page); continue
            else:
                done_votes = 0

            if phase == "done":
                report["status"] = "completed"
                report["final_text"] = obs.text[:500]
                report["final_text_full"] = obs.text
                self.learner.learn_results_markers(obs.url, obs.text)
                m = SCORE_RX.search(obs.text)
                report["final_score_text"] = m.group(0) if m else None
                score_msg = f" | Verified Result: {report['final_score_text']}" if report['final_score_text'] else ""
                print(f" [AssessPilot] 🏁 Assessment completed successfully!{score_msg}")
                return

            if phase == "unknown":
                unknown += 1
                if unknown > 12:
                    report["status"] = "failed: nothing actionable on page (adapter can't see questions/buttons)"
                    return
                time.sleep(0.5); self.settle(page); continue
            unknown = 0

            sig = obs.sig()
            stuck = stuck + 1 if sig == last_sig else 0
            last_sig = sig
            if stuck == 2:
                applied.clear()
                report["warnings"].append(f"step {n}: no progress, re-applying answers")
            if stuck >= 4:
                blank = [q.prompt[:50] for q in obs.questions if not q.answered]
                report["status"] = f"failed: stuck in phase '{phase}' (page not advancing)" + (f"; unanswered: {blank}" if blank else "")
                return

            if phase == "login":
                self.login(page, ctx, url)
                continue

            if phase == "start":
                nav = self.pick(obs, "start") or self.pick(obs, "next")
                print(f" [Step {n+1:02d}] 🚀 Starting Assessment: Clicking '{nav.text}'")
                rec["click"] = nav.text
                page, ad = self._click_nav(ctx, nav.loc, page, ad); continue

            if phase == "confirm":
                nav = self.pick_confirm(obs)
                if not nav:
                    report["status"] = "failed: modal open with no confirm button"
                    return
                print(f" [Step {n+1:02d}] ⚠️  Confirming submission: Clicking '{nav.text}'")
                rec["click"] = nav.text
                if pending or re.search(r"submit|finish|turn in|end", nav.text, re.I):
                    pending = True
                beh.pause(rng, beh.action_gap)
                page, ad = self._click_nav(ctx, nav.loc, page, ad); continue

            if phase == "summary":
                beh.pause(rng, beh.review_pause)
                nav = self.pick(obs, "submit")
                print(f" [Step {n+1:02d}] 📋 Summary reached: Clicking '{nav.text}'")
                rec["click"] = nav.text
                pending = True
                page, ad = self._click_nav(ctx, nav.loc, page, ad); continue

            # ---- questions
            if revisit and self.pick(obs, "prev"):
                revisit = False
                nav = self.pick(obs, "prev")
                rec["click"] = nav.text + " (revisit)"
                page, ad = self._click_nav(ctx, nav.loc, page, ad); continue
            revisit = False

            todo = []
            for q in obs.questions:
                prev = applied.get(q.key)
                if prev is None or (q.reliable and not self.matches(q, prev)):
                    todo.append(q)
            rec["applied"] = []
            if todo:
                print(f" [Step {n+1:02d}] 📝 Answering {len(todo)} questions on page...")
            for i, q in enumerate(todo):
                ch = self.strategy.choose(q)
                if ch is None:
                    applied[q.key] = SKIPPED
                    rec["applied"].append({"prompt": q.prompt[:80], "skipped": True})
                    print(f"   [Skip] Q{i+1}: {q.prompt[:55]}... (no answer)")
                    continue
                beh.pause(rng, beh.think, beh.read_time(q.prompt))
                warn = self.apply(q, ch)
                report["warnings"] += [f"step {n}: {w}" for w in warn]
                applied[q.key] = ch
                chosen = ch.texts(q)
                self.answers[q.key] = {"prompt": q.prompt, "kind": q.kind, "fp": q.fp, "chosen": chosen, "source": ch.source,
                                       "options": [o.text for o in q.options]}
                rec["applied"].append({"prompt": q.prompt[:80], "chosen": chosen, "source": ch.source})
                chosen_disp = ", ".join(chosen) if chosen else ch.text or "Selected"
                print(f"   [Ans]  Q{i+1}: {q.prompt[:55]}... -> {chosen_disp} [{ch.source}]")
            if todo:
                beh.pause(rng, beh.action_gap)

            nav = self.pick(obs, "next")
            if nav is None:
                # maybe enabled only after answering: re-read once
                time.sleep(0.3)
                obs2 = ad.observe(page)
                nav = self.pick(obs2, "next") or self.pick(obs2, "submit")
            if nav is None:
                time.sleep(0.5); self.settle(page); continue
            rec["click"] = nav.text
            print(f" [Step {n+1:02d}] ➡️  Navigating: Clicking '{nav.text}'")
            if nav.action == "submit":
                pending = True
            revisit = nav.action == "next" and rng.random() < beh.revisit_p
            page, ad = self._click_nav(ctx, nav.loc, page, ad)
        # max steps reached -> status stays 'running' -> converted by caller

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def phase(obs: Obs, pending: bool) -> str:
        if obs.done_marker and not obs.questions and not obs.modal_navs:
            return "done"
        if obs.modal_navs:
            return "confirm"
        if obs.questions:
            return "questions"
        if obs.login:
            return "login"
        acts = {n.action for n in obs.navs if not n.disabled}
        if pending:
            return "summary" if "submit" in acts else "done?"
        if "start" in acts:
            return "start"
        if "submit" in acts:
            return "summary"
        return "unknown"

    @staticmethod
    def pick(obs: Obs, action: str):
        for n in obs.navs:
            if n.action == action and not n.disabled and not n.modal:
                return n
        return None

    @staticmethod
    def pick_confirm(obs: Obs):
        c = [n for n in obs.modal_navs if n.action == "confirm" and not n.disabled]
        return c[0] if c else None

    @staticmethod
    def matches(q, ch: Choice) -> bool:
        if ch.source == "skip":
            return True
        if q.kind in TEXT_KINDS or q.kind == "select" or q.mode == "select":
            return q.answered
        return {i for i, o in enumerate(q.options) if o.checked} == set(ch.indices)

    def rebind(self, q):
        """Page re-rendered (stamps lost): re-scan and swap in fresh locators for this question."""
        obs = self._ad.observe(self._page)
        for nq in obs.questions:
            if nq.key == q.key:
                q.options, q.ctrl, q.frame, q.answered = nq.options, nq.ctrl, nq.frame, nq.answered
                return True
        return False

    def ensure(self, q):
        try:
            if q.ctrl.count() == 1:
                return
        except Exception:
            pass
        self.rebind(q)

    def click_opt(self, q, i, jitter=None):
        for _ in range(3):
            try:
                if q.options[i].click.count() == 1:
                    return self.click(q.options[i].click, jitter)
            except Exception:
                pass
            self.rebind(q)
        raise RuntimeError(f"option locator lost after re-render: {q.prompt[:40]!r}")

    def opt_on(self, q, i) -> bool:
        try:
            if q.options[i].state.count() != 1:
                self.rebind(q)
            return bool(q.options[i].state.evaluate(STATE_JS))
        except Exception:
            return False

    def click(self, loc, jitter=None):
        jitter = self.beh.click_jitter if jitter is None else jitter
        try:
            loc.scroll_into_view_if_needed(timeout=2500)
        except Exception:
            pass
        try:
            if jitter:
                box = loc.bounding_box()
                if box and box["width"] > 8 and box["height"] > 8:
                    loc.click(position={"x": self.rng.uniform(.2, .8) * box["width"], "y": self.rng.uniform(.25, .75) * box["height"]}, timeout=3000)
                    return
            loc.click(timeout=3000)
        except Exception:
            try:
                loc.click(force=True, timeout=2000)
            except Exception:
                try:
                    loc.dispatch_event("click", timeout=2000)
                except Exception:
                    pass

    def apply(self, q, ch: Choice) -> list[str]:
        beh, rng, warn = self.beh, self.rng, []
        self.ensure(q)
        if q.kind in TEXT_KINDS:
            text = ch.text or ""
            q.ctrl.click(timeout=3000)
            q.ctrl.fill("")
            if beh.type_cps:
                q.ctrl.press_sequentially(text, delay=1000 / beh.type_cps / max(beh.speed, 0.01))
            else:
                q.ctrl.fill(text)
            try:
                q.ctrl.evaluate("e => e.blur()")
            except Exception:
                pass
            return warn
        if q.mode == "select":
            if q.kind == "multi":
                q.ctrl.select_option(index=[q.options[i].idx for i in ch.indices])
            else:
                q.ctrl.select_option(index=q.options[ch.indices[0]].idx)
            return warn
        opts = q.options
        if q.kind == "single":
            want = ch.indices[0]
            if len(opts) > 1 and rng.random() < beh.change_answer_p:
                other = rng.choice([i for i in range(len(opts)) if i != want])
                self.click_opt(q, other)
                beh.pause(rng, beh.action_gap)
            if q.mode == "heur" or not self.opt_on(q, want):
                self.click_opt(q, want)
            if q.reliable and not self.opt_on(q, want):
                self.click_opt(q, want, jitter=False)
                if not self.opt_on(q, want):
                    try:
                        q.options[want].click.click(force=True)
                    except Exception:
                        pass
                    if not self.opt_on(q, want):
                        warn.append(f"option not selected after retries: {q.prompt[:40]!r} -> {opts[want].text!r}")
            return warn
        # multi
        want = set(ch.indices)
        for i in range(len(opts)):
            if q.reliable:
                if self.opt_on(q, i) != (i in want):
                    self.click_opt(q, i)
                    beh.pause(rng, beh.action_gap)
            elif i in want:
                self.click_opt(q, i)
        if q.reliable:
            bad = [i for i in range(len(opts)) if self.opt_on(q, i) != (i in want)]
            if bad:
                warn.append(f"multi-select mismatch: {q.prompt[:40]!r} options {bad}")
        return warn

    def login(self, page, ctx, url):
        cur_url = page.url.lower()
        is_google_or_oauth = (
            "accounts.google.com" in cur_url
            or "login.microsoftonline.com" in cur_url
            or "/oauth" in cur_url
            or "/signin" in cur_url
            or "google" in cur_url
        )
        pwd = page.locator("input[type=password]:visible").first

        # Interactive OAuth / Google Login or login without credentials:
        if is_google_or_oauth or not self.creds or pwd.count() == 0:
            if self.headed:
                print("\n" + "=" * 70)
                print(" [AssessPilot] 🔑 Interactive Login / Google Sign-In Detected")
                print(f" Current URL: {page.url}")
                print(" -> Please complete sign-in in the open browser window.")
                print(" -> AssessPilot will automatically detect when login succeeds and continue.")
                print("=" * 70 + "\n")

                t0 = time.time()
                while time.time() - t0 < 300:  # 5 minutes grace period
                    time.sleep(1.5)
                    try:
                        new_url = page.url.lower()
                        # If user navigated away from OAuth/login domain or questions appeared
                        if "accounts.google.com" not in new_url and "signin" not in new_url and "login" not in new_url:
                            self.settle(page)
                            obs_test = self._ad.observe(page)
                            if obs_test.questions or not obs_test.login:
                                break
                        obs_test = self._ad.observe(page)
                        if obs_test.questions:
                            break
                    except Exception:
                        pass

                print("[AssessPilot] ✅ Sign-in verified! Capturing session tokens and continuing...")
                sp = self.cache.state_path(url) if self.cache else None
                if sp:
                    try:
                        ctx.storage_state(path=str(sp))
                        sp.chmod(0o600)
                    except Exception:
                        pass
                if self.profile:
                    try:
                        from .browser_launcher import resolve_chrome_profile
                        prof_dir = Path(resolve_chrome_profile(self.profile) or self.profile)
                        sf = prof_dir / "qa_cookies.json"
                        sf.write_text(json.dumps(ctx.cookies()))
                        sf.chmod(0o600)
                        st_file = prof_dir / "qa_storage_state.json"
                        ctx.storage_state(path=str(st_file))
                        st_file.chmod(0o600)
                    except Exception:
                        pass
                self.settle(page)
                return
            else:
                raise RuntimeError(
                    f"Interactive authentication (Google Sign-In / OAuth) required for {page.url}. "
                    "Please run in headed mode ('assesspilot run') to complete sign-in once in the browser window, "
                    "or connect to your running Chrome with '--cdp http://127.0.0.1:9222'."
                )

        # Standard form-based username/password login
        u, pw = self.creds
        form = pwd.locator("xpath=ancestor::form[1]")
        scope = form if form.count() else page
        user = scope.locator("input:not([type=password]):not([type=hidden]):not([type=submit]):not([type=checkbox]):not([type=button]):visible").first
        user.fill(u)
        pwd.fill(pw)
        btn = scope.locator("button[type=submit],input[type=submit],button:not([type])").first
        if btn.count():
            self.click(btn, jitter=False)
        else:
            pwd.press("Enter")
        self.settle(page)
        sp = self.cache.state_path(url) if self.cache else None
        if sp:
            ctx.storage_state(path=str(sp))
            try:
                sp.chmod(0o600)
            except Exception:
                pass
