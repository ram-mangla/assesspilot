"""In-process fake of the browser thread so session/HTTP logic is testable without Playwright.

It mimics `ManualBrowserSession.ctrl(op, **kw)` by delegating to a stub controller that holds
a scripted page: a list of questions, answerable controls, save state and a submit outcome."""
from __future__ import annotations

import re


def mkq(qid, text, options=("A", "B", "C"), qtype="single_choice", index=1, total=3, selected=None, answered=False):
    return {"question_id": qid, "question_text": text, "question_type": qtype,
            "options": [{"id": o, "text": f"Option {o}", "selected": (selected or []).count(o) > 0} for o in options],
            "images": [], "page_url": "https://quiz.test/q", "question_index": index, "total_questions": total,
            "answered": answered, "saved_state_text": "Not yet answered" if not answered else "Answer saved",
            "text_value": "", "text_uid": "t1" if qtype in ("short_answer", "long_answer") else None,
            "selects": [], "position": 1, "progress_text": None}


class StubController:
    def __init__(self, questions=None, controls=None, saved_indicator="Not yet answered", submit_ok=True,
                 score_text="Score: 7 / 10 (70%)", start_ok=True, submit_control="Submit all and finish"):
        self.questions = questions or [mkq("q1", "Capital of France?")]
        self.controls = controls if controls is not None else [
            {"text": "Next", "disabled": False, "in_modal": False, "uid": "n1"},
            {"text": "Finish attempt ...", "disabled": False, "in_modal": False, "uid": "s1"}]
        self.saved_indicator = saved_indicator
        self.submit_ok = submit_ok
        self.score_text = score_text
        self.start_ok = start_ok
        self.submit_control = submit_control
        self.calls: list[tuple] = []
        self.url = "https://quiz.test/q"
        self.title = "Quiz"
        self.submitted = False
        self.results_page: bool | None = None   # None = derive from `submitted`
        self.confirmations: list[bool] = []
        self.index = 0

    # ---- controller surface used by QuizSession
    def status(self, **kw):
        self.calls.append(("status",))
        return {"connected": True, "url": self.url, "title": self.title}

    def inspect(self, **kw):
        return {"url": self.url, "title": self.title, "timer": None, "progress": {"index": self.index + 1, "total": 3},
                "questions": [], "controls": self.controls, "text": self.score_text if self.submitted else "",
                "has_password": False, "nav_items": [], "looks_quiz": True, "ready_state": "complete"}

    def detection(self, **kw):
        self.calls.append(("detection",))
        return {"is_quiz": True, "quiz_title": self.title, "quiz_description": "", "question_count": len(self.questions),
                "current_question": self.questions[self.index] if self.questions else None, "login_required": False,
                "results_page": self.submitted if self.results_page is None else self.results_page,
                "start_control": {"text": "Attempt quiz", "disabled": False, "in_modal": False, "uid": "st"},
                "submit_control": {"text": self.submit_control, "disabled": False, "in_modal": False, "uid": "s1"},
                "controls": {"next": [{"text": "Next", "disabled": False}], "prev": []},
                "navigator_items": 0, "progress": {"index": self.index + 1, "total": 3}, "timer": None,
                "instructions": "", "frames": [], "attempt_status": "active"}

    def extract_questions(self, **kw):
        if not self.questions:
            return []
        q = self.questions[self.index]
        return [{**q, "answered": any(o["selected"] for o in q["options"])}]

    def move_question(self, direction, **kw):
        self.calls.append(("move", direction))
        nxt = self.index + (1 if direction == "next" else -1)
        if not (0 <= nxt < len(self.questions)):
            return {"ok": False, "reason": "no next control found", "before": self.signature()}
        self.index = nxt
        return {"ok": True, "question": self.questions[nxt], "question_index": nxt + 1}

    def jump_to(self, index=1, **kw):
        self.calls.append(("jump", index))
        if not (1 <= index <= len(self.questions)):
            return {"ok": False, "reason": f"the page exposes no question navigator entry for question {index}"}
        self.index = index - 1
        return {"ok": True, "question": self.questions[self.index]}

    def signature(self, **kw):
        q = self.questions[self.index]
        return {"question_id": q["question_id"], "url": self.url, "index": self.index + 1, "text": q["question_text"]}

    def check_question_present(self, question_id="", **kw):
        q = self.questions[self.index]
        present = q["question_id"] == question_id
        return {"present": present, "question": q if present else None, "visible": [q]}

    def current_question(self, **kw):
        return self.questions[self.index]

    def apply_answer(self, question=None, answer=None, **kw):
        self.calls.append(("apply", (answer or {}).get("selected_options")))
        wanted = (answer or {}).get("selected_options") or []
        ids = {o["id"] for o in (question or {}).get("options", [])}
        bad = [w for w in wanted if w not in ids]
        if bad:
            return {"applied": False, "reason": f"answer names option(s) not on this question: {bad}"}
        for o in question["options"]:
            o["selected"] = o["id"] in wanted
        return {"applied": True, "verified": {"matches": True, "observed": wanted}}

    def save_answer(self, **kw):
        self.calls.append(("save",))
        saved = "saved" in self.saved_indicator.lower()
        return {"saved": saved, "indicator": self.saved_indicator}

    def start_attempt(self, **kw):
        self.calls.append(("start_attempt",))
        return {"started": self.start_ok, "control": "Attempt quiz",
                "question": self.questions[0] if self.questions else None,
                "site_attempt_id": "abc123", "timer": None, "reason": None if self.start_ok else "no question appeared"}

    def submission_preview(self, attempt=None, records=None, **kw):
        qs = self.questions
        return {"attempt_id": (attempt or {}).get("attempt_id"), "total_questions": len(qs),
                "answered": sum(1 for q in qs if any(o["selected"] for o in q["options"])),
                "unanswered": [i + 1 for i, q in enumerate(qs) if not any(o["selected"] for o in q["options"])],
                "unsaved": [r["question_id"] for r in records or [] if r.get("applied")],
                "flagged": [r["question_id"] for r in records or [] if r.get("flagged")],
                "conflicts": [], "submit_control": self.submit_control, "requires_confirmation": True}

    def submit(self, confirm=False, **kw):
        self.calls.append(("submit", confirm))
        self.confirmations.append(confirm)
        if not confirm:
            return {"submitted": False, "requires_confirmation": True, "reason": "requires confirmation"}
        if not self.submit_ok:
            return {"submitted": False, "reason": "the page did not confirm submission after the click"}
        self.submitted = True
        if not re.search(r"\d\s*/\s*\d", self.score_text or ""):
            return {"submitted": True, "confirmed_dialog": True,
                    "result": {"score": None, "source": "site confirmation page", "text": self.score_text}}
        return {"submitted": True, "confirmed_dialog": True,
                "result": {"score": {"earned": 7.0, "total": 10.0, "pct": 70.0, "raw": self.score_text},
                           "source": "site result page", "text": self.score_text}}

    def screenshot(self, **kw):
        return "data:image/jpeg;base64,AAA"

    def tabs(self, **kw):
        return [{"index": 0, "url": self.url, "title": self.title, "current": True}]

    def adopt_popup(self, **kw):
        return {"adopted": False}

    def navigate(self, url="", **kw):
        self.url = url
        return {"url": url, "title": self.title, "redirected": False}

    def reload(self, **kw):
        return {"url": self.url, "title": self.title}

    def back(self, **kw):
        return {"url": self.url, "title": self.title}


class FakeBrowser:
    """Same surface as ManualBrowserSession (start/ctrl/select_tab/stop)."""

    def __init__(self, controller=None):
        self.controller = controller or StubController()
        self.started: list = []

    def start(self, url=None, headed=True, profile=None, cdp=None):
        self.started.append((url, headed))
        self.controller.url = url
        return {"connected": True, "url": url, "title": self.controller.title}

    def ctrl(self, op, timeout=45.0, **kw):
        return getattr(self.controller, op)(**kw)

    def select_tab(self, index):
        return {"connected": True}

    def stop(self):
        return None
