"""Playwright controller for one visible, isolated browser context.

Runs on the same worker thread that owns Playwright (session.py), so it never touches a
Playwright object from another thread. Exposes navigation, tab, inspection, question
navigation, answer application and submission as explicit operations; every operation
reports what it observed afterwards, never just that a click returned."""
from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path

from .adapters import classify
from .normalize import fingerprint

_JS = (Path(__file__).with_name("page_inspect.js")).read_text(encoding="utf-8")

TEXT_KINDS = {"text", "textarea", "number", "short_answer", "long_answer"}


class NavError(RuntimeError):
    pass


def classify_control(text: str) -> str | None:
    return classify(text or "", False)


class BrowserController:
    def __init__(self, page, store=None, session_id: str | None = None):
        self.page = page
        self.store = store
        self.session_id = session_id or ""
        self.dialogs: list[str] = []
        self.auto_accept_dialogs = True
        self.pending_dialogs: list[dict] = []
        self.last_ready: dict = {}

    # ------------------------------------------------------------------ inspection
    def is_alive(self) -> bool:
        try:
            return bool(self.page) and not self.page.is_closed()
        except Exception:
            return False

    def inspect(self) -> dict:
        return self.page.evaluate(_JS, {})

    def wait_ready(self, timeout: float = 15.0) -> dict:
        """A document load event does not mean the questions are there: wait for DOM/network
        quiet AND something actionable (questions, a login form, or nav controls)."""
        deadline = time.time() + timeout
        last = {}
        while time.time() < deadline:
            try:
                last = self.inspect()
            except Exception:
                time.sleep(0.3)
                continue
            settled = last.get("ready_state") == "complete" and not last.get("busy")
            has_target = bool(last.get("questions")) or last.get("has_password") or bool(last.get("controls"))
            if settled and has_target:
                self.last_ready = last
                return last
            try:
                self.page.wait_for_timeout(250)
            except Exception:
                time.sleep(0.25)
        self.last_ready = last
        last["ready_timeout"] = True
        return last

    def status(self) -> dict:
        if not self.is_alive():
            return {"connected": False, "url": None, "title": None, "tabs": [], "current_tab": None}
        pg = self.page
        tabs = self.tabs()
        return {"connected": True, "url": pg.url, "title": self._safe_title(pg),
                "current_tab": next((t["index"] for t in tabs if t["current"]), None),
                "loading": self._loading(), "dialogs": self.dialogs[-5:], "session_id": self.session_id}

    @staticmethod
    def _safe_title(pg) -> str:
        try:
            return pg.title()
        except Exception:
            return ""

    def _loading(self) -> bool:
        try:
            return self.page.evaluate("() => document.readyState !== 'complete'")
        except Exception:
            return False

    def screenshot(self, full_page: bool = False) -> str:
        raw = self.page.screenshot(type="jpeg", quality=70, full_page=full_page)
        return "data:image/jpeg;base64," + base64.b64encode(raw).decode()

    def accessible_text(self) -> str:
        try:
            return self.page.evaluate("() => document.body ? document.body.innerText : ''")[:6000]
        except Exception:
            return ""

    # ------------------------------------------------------------------ navigation
    def navigate(self, url: str, timeout: float = 30000) -> dict:
        from .session import validate_url
        target = validate_url(url)
        self.page.goto(target, wait_until="domcontentloaded", timeout=timeout)
        return {"url": self.page.url, "title": self._safe_title(self.page),
                "redirected": self.page.url.split("#")[0] != target.split("#")[0]}

    def reload(self) -> dict:
        self.page.reload(wait_until="domcontentloaded", timeout=30000)
        return {"url": self.page.url, "title": self._safe_title(self.page)}

    def back(self) -> dict:
        try:
            self.page.go_back(wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            return {"url": self.page.url, "error": f"back failed: {e}"}
        return {"url": self.page.url, "title": self._safe_title(self.page)}

    def forward(self) -> dict:
        try:
            self.page.go_forward(wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            return {"url": self.page.url, "error": f"forward failed: {e}"}
        return {"url": self.page.url, "title": self._safe_title(self.page)}

    # ------------------------------------------------------------------ tabs
    def tabs(self) -> list[dict]:
        out = []
        try:
            for i, p in enumerate(self.page.context.pages):
                out.append({"index": i, "url": p.url, "title": self._safe_title(p), "current": p is self.page,
                            "closed": p.is_closed()})
        except Exception:
            pass
        return out

    def switch_tab(self, index: int) -> dict:
        pages = self.page.context.pages
        if not (0 <= index < len(pages)):
            raise NavError(f"tab {index} does not exist (have {len(pages)})")
        self.page = pages[index]
        self.page.bring_to_front()
        return self.status()

    def new_tab(self, url: str | None = None) -> dict:
        self.page = self.page.context.new_page()
        if url:
            self.navigate(url)
        return self.status()

    def adopt_popup(self, timeout: float = 5.0, timeout_s: float | None = None) -> dict:
        limit = timeout_s if timeout_s is not None else timeout
        known = list(self.page.context.pages)
        deadline = time.time() + limit
        while time.time() < deadline:
            new = [p for p in self.page.context.pages if p not in known]
            if new:
                self.page = new[-1]
                return {"adopted": True, **self.status()}
            time.sleep(0.1)
        return {"adopted": False}

    # ------------------------------------------------------------------ dialogs
    def attach_dialog_handler(self) -> None:
        def on_dialog(d):
            self.dialogs.append(f"{d.type}: {d.message}"[:200])
            if self.auto_accept_dialogs:
                try:
                    d.accept()
                    return
                except Exception:
                    pass
            self.pending_dialogs.append({"type": d.type, "message": d.message[:200]})
            try:
                d.dismiss()
            except Exception:
                pass
        self.page.on("dialog", on_dialog)

    # ------------------------------------------------------------------ question extraction
    def extract_questions(self, ins: dict | None = None) -> list[dict]:
        ins = ins or self.inspect()
        progress = ins.get("progress") or {}
        total = progress.get("total")
        idx0 = progress.get("index")
        raw = ins.get("questions") or []
        out = []
        for i, d in enumerate(raw):
            qtype = self._type_of(d)
            index = d.get("number") or (idx0 + i if (idx0 and len(raw) == 1) else (i + 1))
            options = [{"id": (o.get("value") or chr(65 + k)), "text": o.get("text", ""),
                        "selected": bool(o.get("checked")), "uid": o.get("uid"), "click_uid": o.get("click")}
                       for k, o in enumerate(d.get("options") or [])]
            if d.get("kind") == "select" and len(d.get("selects") or []) == 1:
                s = d["selects"][0]
                options = [{"id": o["text"] or o["value"], "text": o["text"], "value": o["value"],
                            "selected": o["value"] == s.get("value")} for o in s.get("options", []) if o.get("value") != ""]
            qid = fingerprint(d.get("prompt", ""), [o["text"] for o in options]) or f"pos{index}"
            images = [] if not d.get("has_images") else [im.get("src") for im in ins.get("images") or [] if im.get("src")][:4]
            out.append({
                "question_id": qid,
                "question_text": d.get("prompt", ""),
                "question_type": qtype,
                "kind": d.get("kind"),
                "options": options,
                "images": images,
                "page_url": ins.get("url"),
                "question_index": index,
                "total_questions": total,
                "answered": bool(d.get("answered")),
                "saved_state_text": d.get("saved_state") or "",
                "text_value": d.get("text_value") or "",
                "text_uid": d.get("text_uid"),
                "box_uid": d.get("box"),
                "selects": d.get("selects") or [],
                "position": d.get("position") or (i + 1),
                "progress_text": d.get("progress"),
            })
        return out

    @staticmethod
    def _type_of(d: dict) -> str:
        k = d.get("kind")
        texts = [(o.get("text") or "").strip().lower() for o in d.get("options") or []]
        if k == "single" and sorted(texts) == ["false", "true"]:
            return "true_false"
        if d.get("has_images") and not texts:
            return "image"
        return {"single": "single_choice", "multi": "multiple_choice", "select": "single_choice",
                "matching": "matching", "text": "short_answer", "textarea": "long_answer",
                "number": "short_answer"}.get(k, "short_answer")

    def current_question(self, questions: list[dict] | None = None) -> dict | None:
        qs = questions if questions is not None else self.extract_questions()
        return qs[0] if qs else None

    def detection(self) -> dict:
        ins = self.wait_ready()
        questions = self.extract_questions(ins)
        controls = ins.get("controls") or []
        by_action: dict[str, list[dict]] = {}
        for c in controls:
            a = classify_control(c["text"])
            if a:
                by_action.setdefault(a, []).append(c)
        start = [c for c in controls if re.match(r"^(start|begin|attempt|take|resume|continue)\b", c["text"], re.I)]
        submit = [c for c in controls if re.search(r"submit|finish|turn in|finali[sz]e", c["text"], re.I)
                  and not c.get("in_modal")]
        progress = ins.get("progress") or {}
        return {
            "is_quiz": bool(ins.get("looks_quiz")),
            "quiz_title": ins.get("title"),
            "instructions": (ins.get("text") or "")[:600],
            "start_control": start[0] if start else None,
            "submit_control": submit[0] if submit else None,
            "question_count": len(questions),
            "current_question": questions[0] if questions else None,
            "controls": {k: [{"text": c["text"], "disabled": c["disabled"]} for c in v] for k, v in by_action.items()},
            "navigator_items": len(ins.get("nav_items") or []),
            "progress": progress,
            "timer": ins.get("timer"),
            "login_required": bool(ins.get("has_password")),
            "results_page": self._looks_like_results(ins),
            "attempt_status": "active" if questions else ("pre_start" if start else "unknown"),
            "frames": [{"url": f.url, "name": f.name} for f in self.page.frames][:10],
            "ready_timeout": bool(ins.get("ready_timeout")),
        }

    @staticmethod
    def _looks_like_results(ins: dict) -> bool:
        if ins.get("questions"):
            return False
        t = (ins.get("text") or "").lower()
        return bool(re.search(r"(your (final )?grade|score|marks? obtained|quiz results|attempt (summary|finished))", t))

    # ------------------------------------------------------------------ controls
    def _control(self, patterns, *, actions=None, allow_modal: bool = False) -> dict | None:
        ins = self.inspect()
        cands = []
        for c in ins.get("controls") or []:
            if c.get("in_modal") and not allow_modal:
                continue
            if actions:
                if classify_control(c["text"]) not in actions:
                    continue
            elif not any(re.search(p, c["text"], re.I) for p in patterns):
                continue
            cands.append(c)
        cands.sort(key=lambda c: (bool(c.get("disabled")), not bool(c.get("in_modal")), len(c["text"])))
        return cands[0] if cands else None

    def _loc(self, uid: str):
        """Frame-aware lookup: main document first, then same-origin child frames."""
        loc = self.page.locator(f'[data-qa="{uid}"]')
        if loc.count():
            return loc.first
        for f in self.page.frames:
            if f is self.page.main_frame:
                continue
            l = f.locator(f'[data-qa="{uid}"]')
            if l.count():
                return l.first
        return self.page.locator(f'[data-qa="{uid}"]').first

    def _click_uid(self, uid: str, timeout: float) -> None:
        loc = self._loc(uid)
        if loc.count() == 0:
            raise NavError("control disappeared from the page")
        loc.scroll_into_view_if_needed(timeout=2000)
        loc.click(timeout=timeout)

    def click_selector(self, selector: str, timeout: float = 30000) -> dict:
        """Playwright-selector click, frame-aware. Used for third-party flows (login/SSO)."""
        loc = self.page.locator(selector)
        if loc.count() == 0:
            for f in self.page.frames:
                l = f.locator(selector)
                if l.count():
                    loc = l
                    break
        if loc.count() == 0:
            return {"clicked": False, "reason": f"nothing matches {selector!r}"}
        loc.first.scroll_into_view_if_needed(timeout=2000)
        loc.first.click(timeout=timeout)
        return {"clicked": True, "selector": selector, "url": self.page.url}

    def eval_js(self, expression: str, arg=None) -> dict:
        """Evaluate a JS expression on the page. Read-only probes and third-party DOM reads."""
        return {"ok": True, "value": self.page.evaluate(expression, arg)}

    # ------------------------------------------------------------------ question navigation
    def signature(self) -> dict:
        qs = self.extract_questions()
        q = qs[0] if qs else None
        return {"question_id": q["question_id"] if q else None, "url": self.page.url.split("#")[0],
                "index": q["question_index"] if q else None,
                "text": (q["question_text"] or "")[:120] if q else None}

    def _wait_question_change(self, before: dict, timeout: float = 15.0) -> dict:
        deadline = time.time() + timeout
        after = before
        changed = False
        while time.time() < deadline:
            try:
                after = self.signature()
            except Exception:
                self.page.wait_for_timeout(250)
                continue
            if after["question_id"] and after["question_id"] != before["question_id"]:
                changed = True
                break
            if after["index"] and before["index"] and after["index"] != before["index"]:
                changed = True
                break
            self.page.wait_for_timeout(250)
        return {"changed": changed, "before": before, "after": after}

    def move_question(self, direction: str, timeout: float = 15.0) -> dict:
        before = self.signature()
        patterns = (r"^(next|continue|proceed|save (&|and) (next|continue|page))",) if direction == "next" else \
                   (r"^(prev|previous|back|go back)",)
        ctl = self._control(patterns, actions=("next",) if direction == "next" else ("prev",))
        if not ctl:
            return {"ok": False, "reason": f"no {direction} control found", "before": before,
                    "diagnostics": self.diagnostics()}
        if ctl.get("disabled"):
            return {"ok": False, "reason": f"{direction} control is disabled (an answer may be required first)",
                    "control": ctl["text"], "before": before}
        try:
            self._click_uid(ctl["uid"], timeout=5000)
        except Exception as e:
            return {"ok": False, "reason": f"click failed: {e}", "control": ctl["text"], "before": before}
        res = self._wait_question_change(before, timeout)
        if not res["changed"]:
            return {"ok": False, "reason": f"question did not change within {timeout}s after clicking {ctl['text']!r}",
                    "control": ctl["text"], "before": before, "after": res["after"], "diagnostics": self.diagnostics()}
        qs = self.extract_questions()
        return {"ok": True, "control": ctl["text"], "before": before, "question": qs[0] if qs else None,
                "question_index": qs[0]["question_index"] if qs else None,
                "total_questions": qs[0]["total_questions"] if qs else None}

    def jump_to(self, index: int, timeout: float = 15.0) -> dict:
        ins = self.inspect()
        item = next((n for n in ins.get("nav_items") or [] if n["n"] == index), None)
        if not item:
            return {"ok": False, "reason": f"the page exposes no question navigator entry for question {index}"}
        before = self.signature()
        self._click_uid(item["uid"], timeout=5000)
        res = self._wait_question_change(before, timeout)
        qs = self.extract_questions()
        return {"ok": res["changed"], "question": qs[0] if qs else None,
                "reason": None if res["changed"] else "the displayed question did not change"}

    # ------------------------------------------------------------------ answers
    def check_question_present(self, question_id: str) -> dict:
        qs = self.extract_questions()
        return {"present": any(q["question_id"] == question_id for q in qs),
                "question": next((q for q in qs if q["question_id"] == question_id), None), "visible": qs}

    def apply_answer(self, question: dict, answer: dict) -> dict:
        """Select/enter the answer on the real control and verify the resulting state.
        Exact option matching only; no forced clicks through disabled or missing controls."""
        want_ids = [str(x) for x in (answer.get("selected_options") or [])]
        text = answer.get("answer_text") or ""
        if not want_ids and not text:
            return {"applied": False, "reason": "answer carries neither options nor text"}
        opts = question.get("options") or []
        if want_ids and not opts:
            return {"applied": False, "reason": "question has no selectable options"}
        matched, unmatched = [], []
        norm = lambda s: re.sub(r"^[a-z][.)]\s+", "", (s or "").strip(), flags=re.I).strip().lower()
        if want_ids:
            for want in want_ids:
                hit = next((o for o in opts if str(o["id"]).strip().lower() == want.strip().lower()), None)
                if hit is None:
                    hit = next((o for o in opts if (o.get("text") or "").strip() == want.strip()), None)
                (matched if hit else unmatched).append(hit or want)
            if unmatched:
                return {"applied": False, "reason": f"answer names option(s) not on this question: {unmatched}"}
        elif text and opts:
            matched = [o for o in opts if norm(o.get("text")) == norm(text)]
            if not matched:
                return {"applied": False, "reason": f"answer text {text!r} does not match any displayed option"}
        elif not opts and not text:
            return {"applied": False, "reason": "question has no selectable options"}
        qtype = question.get("question_type")
        try:
            if qtype in TEXT_KINDS and not opts:
                uid = question.get("text_uid")
                if not uid:
                    return {"applied": False, "reason": "no text field found for this question"}
                loc = self._loc(uid)
                if loc.count() == 0 or not loc.is_visible() or not loc.is_enabled():
                    return {"applied": False, "reason": "text field is not actionable"}
                loc.fill("")
                loc.fill(text)
                loc.evaluate("e => e.blur()")
            elif question.get("selects") and not any(o.get("click_uid") for o in matched):
                sel = question["selects"][0]
                loc = self._loc(sel["uid"])
                if loc.count() == 0 or not loc.is_enabled():
                    return {"applied": False, "reason": "dropdown is not actionable"}
                loc.select_option(label=matched[0].get("id"))
            else:
                if not matched:
                    return {"applied": False, "reason": "no matching option control on the page"}
                multi = qtype == "multiple_choice"
                for o in matched:
                    uid = o.get("click_uid") or o.get("uid")
                    loc = self._loc(uid)
                    if loc.count() == 0 and len(matched) > 1:
                        # one-page apps may rerender after each click, invalidating scanned uids
                        fresh = (self.check_question_present(question["question_id"]).get("question")) or {}
                        ref = next((x for x in fresh.get("options") or [] if x.get("id") == o.get("id")), None)
                        if ref and (ref.get("click_uid") or ref.get("uid")):
                            o["click_uid"], o["uid"] = ref.get("click_uid"), ref.get("uid")
                            loc = self._loc(o["click_uid"] or o["uid"])
                    if loc.count() == 0:
                        return {"applied": False, "reason": f"option control vanished: {o.get('text')}"}
                    if not loc.is_enabled():
                        return {"applied": False, "reason": f"option is disabled: {o.get('text')}"}
                    if not o.get("selected"):
                        loc.scroll_into_view_if_needed(timeout=2000)
                        loc.click(timeout=4000)
                if not multi:  # leave unintended choices unselected
                    for o in opts:
                        if o not in matched and o.get("selected"):
                            uid = o.get("click_uid") or o.get("uid")
                            loc = self.page.locator(f'[data-qa="{uid}"]').first
                            if loc.count():
                                loc.click(timeout=4000)
        except Exception as e:
            return {"applied": False, "reason": f"interaction failed: {type(e).__name__}: {e}"}
        verified = self.verify_answer(question["question_id"], matched, text, qtype, question)
        return {"applied": verified["matches"], "verified": verified, "reason": verified.get("reason")}

    def verify_answer(self, question_id: str, matched: list, text: str, qtype: str, expected_q: dict | None = None) -> dict:
        q = self.check_question_present(question_id).get("question") or expected_q
        if not q:
            return {"matches": False, "reason": "question no longer displayed"}
        if qtype in TEXT_KINDS and not q.get("options"):
            got = (q.get("text_value") or "").strip()
            ok = got == (text or "").strip() and bool(got)
            return {"matches": ok, "observed": got, "expected": text,
                    "reason": None if ok else "entered text does not match the requested answer"}
        selected = {str(o["id"]).lower() for o in q["options"] if o.get("selected")}
        want = {str(o["id"]).lower() for o in matched if isinstance(o, dict)}
        ok = selected == want if qtype == "multiple_choice" else want.issubset(selected)
        return {"matches": ok, "observed": sorted(selected), "expected": sorted(want),
                "reason": None if ok else "control state does not match the requested answer"}

    def save_answer(self, timeout: float = 6.0) -> dict:
        """Use the page's own save control when it has one, then look for a saved indicator.
        A click that returns is not proof of a save."""
        ctl = next((c for c in (self.inspect().get("controls") or [])
                    if re.search(r"^(save|check answer|submit answer|save answer)", c["text"], re.I)
                    and not c.get("in_modal")), None)
        clicked = None
        if ctl:
            if ctl.get("disabled"):
                return {"saved": False, "reason": f"save control {ctl['text']!r} is disabled"}
            self._click_uid(ctl["uid"], timeout=5000)
            clicked = ctl["text"]
        deadline = time.time() + timeout
        seen = ""
        while time.time() < deadline:
            ins = self.inspect()
            state = " ".join((d.get("saved_state") or "") for d in ins.get("questions") or [])
            seen = state[:120]
            if re.search(r"saved|answered|recorded|complete|submitted", state, re.I):
                return {"saved": True, "indicator": seen, "clicked": clicked}
            if re.search(r"not (yet )?answered|unsaved|not saved", state, re.I):
                return {"saved": False, "indicator": seen, "clicked": clicked,
                        "reason": "page reports the answer as not saved"}
            self.page.wait_for_timeout(300)
        return {"saved": False, "clicked": clicked, "indicator": seen or None,
                "reason": ("saved state is not visible on the page after the save control was clicked"
                           if clicked else "this page exposes no save control or saved indicator")}

    # ------------------------------------------------------------------ attempt lifecycle
    def start_attempt(self) -> dict:
        ctl = self._control((r"^(start|begin|attempt|take|resume|continue)\b",), actions=("start",))
        if not ctl:
            return {"started": False, "reason": "no start/begin control on the page"}
        if ctl.get("disabled"):
            return {"started": False, "reason": f"start control {ctl['text']!r} is disabled"}
        before = self.signature()
        self._click_uid(ctl["uid"], timeout=6000)
        res = self._wait_question_change(before, timeout=20.0)
        qs = self.extract_questions()
        detected = bool(qs)
        m = re.search(r"/a/(\w{4,})", self.page.url)
        return {"started": detected, "control": ctl["text"], "question": qs[0] if qs else None,
                "site_attempt_id": m.group(1) if m else None, "timer": self.inspect().get("timer"),
                "reason": None if detected else "no question appeared after the start click (not clicked again)"}

    def submission_preview(self, attempt: dict, records: list[dict]) -> dict:
        ins = self.inspect()
        qs = self.extract_questions(ins)
        flagged = [r["question_id"] for r in records if r.get("flagged")]
        unsaved = [r["question_id"] for r in records if r.get("applied") and not r.get("saved")]
        conflicts = [r["question_id"] for r in records if r.get("saved_state") == "conflict"]
        ctl = self._control((r"finish|submit|turn in",))
        return {
            "attempt_id": attempt.get("attempt_id"),
            "attempt_status": attempt.get("status"),
            "total_questions": max(len(qs), attempt.get("total_questions") or 0),
            "answered": sum(1 for q in qs if q.get("answered")),
            "unanswered": [q["question_index"] for q in qs if not q.get("answered")],
            "unsaved": unsaved,
            "flagged": flagged,
            "conflicts": conflicts,
            "submit_control": (ctl or {}).get("text"),
            "requires_confirmation": True,
        }

    def submit(self, *, confirm: bool, timeout: float = 30.0) -> dict:
        ctl = self._control((r"^(submit|finish|turn in|end (the )?(quiz|test|attempt))", r"submit all", r"finish attempt"))
        if not ctl:
            return {"submitted": False, "reason": "no submit/finish control on the page"}
        if ctl.get("disabled"):
            return {"submitted": False, "reason": f"submit control {ctl['text']!r} is disabled"}
        if not confirm:
            return {"submitted": False, "requires_confirmation": True, "control": ctl["text"],
                    "reason": "final submission requires explicit confirmation"}
        self.auto_accept_dialogs = True
        self._click_uid(ctl["uid"], timeout=6000)
        def _modal_submit() -> dict | None:
            for t in ("Submit all and finish", "Yes, submit", "Submit", "Finish attempt", "Confirm"):
                c = self._control((rf"^{re.escape(t)}$",), allow_modal=True)
                if c and not c.get("disabled"):
                    return c
            return None

        deadline = time.time() + timeout
        confirmed = False
        while time.time() < deadline:
            ins = self.inspect()
            modal_confirm = _modal_submit()
            if modal_confirm:
                self._click_uid(modal_confirm["uid"], timeout=5000)
                confirmed = True
                continue  # ins predates the click; re-inspect before judging the break conditions
            if self._looks_like_results(ins):
                break
            if confirmed and not ins.get("questions"):
                break
            self.page.wait_for_timeout(400)
        ins = self.inspect()
        from .report import parse_score
        text = ins.get("text") or ""
        results = self._looks_like_results(ins)
        submitted = results or bool(re.search(r"(attempt (submitted|finished)|review|thank you)", text, re.I))
        return {"submitted": submitted, "confirmed_dialog": confirmed,
                "result": {"score": parse_score(text), "source": "site result page", "text": text[:400]}
                if results else None,
                "url": self.page.url,
                "reason": None if submitted else "the page did not confirm submission after the click"}

    def diagnostics(self) -> dict:
        try:
            ins = self.inspect()
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}
        return {"url": ins.get("url"), "title": ins.get("title"), "ready_state": ins.get("ready_state"),
                "questions": len(ins.get("questions") or []),
                "controls": [c["text"] for c in (ins.get("controls") or [])][:10],
                "text": (ins.get("text") or "")[:300]}

    @staticmethod
    def jsonable(obj) -> str:
        return json.dumps(obj, default=str)
