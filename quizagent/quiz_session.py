"""Quiz session orchestration: binds the state machine, the browser controller (running on
the Playwright thread) and the LLM gateway (running on the HTTP thread).

The gateway call happens outside the browser thread, so a slow provider never blocks the
page; every page operation goes through `ManualBrowserSession.ctrl`."""
from __future__ import annotations

import threading
import time
import uuid

from . import session_state as S
from .llm.gateway import Gateway
from .question_navigator import AnswerApplier, QuestionNavigator, SaveManager

MODES = {"observe", "assist", "assisted_attempt", "practice_automation"}


class QuizSession:
    def __init__(self, browser, store=None, gateway: Gateway | None = None, session_id: str | None = None):
        self.browser = browser
        self.store = store
        self.gateway = gateway or Gateway(store=store)
        self.state = S.SessionState(session_id)
        self.attempt: dict = {}
        self.current: dict | None = None
        self.last_answer: dict | None = None
        self.mode = "assist"
        self.auto_submit = False           # off by default, deliberate per-session opt-in
        self.paused = threading.Event()
        self.stopped = threading.Event()
        self.runner: threading.Thread | None = None
        self.lock = threading.RLock()
        self.log: list[dict] = []
        self.last_error: str | None = None
        self.detection: dict = {}

    # ------------------------------------------------------------------ helpers
    def _event(self, kind: str, **data) -> dict:
        rec = {"t": round(time.time(), 3), "kind": kind, **data}
        self.log.append(rec)
        del self.log[:-200]
        return rec

    def _ctrl(self, op: str, timeout: float = 60.0, **kw):
        return self.browser.ctrl(op, timeout=timeout, **kw)

    @property
    def nav(self) -> QuestionNavigator:
        return QuestionNavigator(_CtrlProxy(self))

    @property
    def applier(self) -> AnswerApplier:
        return AnswerApplier(_CtrlProxy(self))

    # ------------------------------------------------------------------ browser lifecycle
    def start(self, url: str, headed: bool = True, profile: str | None = None,
              cdp: str | None = None) -> dict:
        self.state.set(S.BROWSER_STARTING, f"launch {url}")
        try:
            self._event("navigate", url=url)
            res = self.browser.start(url, headed=headed, profile=profile, cdp=cdp)
            det = self._probe_state()
        except Exception as e:
            self.state.set(S.ERROR, f"browser start failed: {e}")
            raise
        return {"started": True, "browser": res, "detection": det, "state": self.state.snapshot()}

    def navigate(self, url: str) -> dict:
        self.state.require(S.NAV_ALLOWED, "navigate")
        with self.state.operation("navigate", S.NAVIGATING):
            res = self._ctrl("navigate", url=url)
            self._probe_state()

        self._event("navigate", url=res.get("url"))
        return {"navigation": res, "state": self.state.snapshot(), **(self.detect() if res else {})}

    def reload(self) -> dict:
        self.state.require(S.NAV_ALLOWED, "refresh")
        with self.state.operation("refresh", S.PAGE_LOADING):
            res = self._ctrl("reload")
            self._probe_state()
        self._event("refresh", url=res.get("url"))
        return {"navigation": res, "state": self.state.snapshot(), **self.detect()}

    def history(self, direction: str) -> dict:
        self.state.require(S.NAV_ALLOWED, f"browser {direction}")
        with self.state.operation(f"browser {direction}", S.NAVIGATING):
            res = self._ctrl("back" if direction == "back" else "forward")
            self._probe_state()
        self._event(f"browser_{direction}", url=res.get("url"))
        return {"navigation": res, "state": self.state.snapshot()}

    def status(self) -> dict:
        det = {}
        try:
            st = self._ctrl("status", timeout=10)
            ins = self._ctrl("inspect", timeout=15)
            det = {"url": ins.get("url"), "title": ins.get("title"), "timer": ins.get("timer"),
                   "progress": ins.get("progress")}
        except Exception as e:
            st = {"connected": False, "error": str(e)}
        snap = {**self.state.snapshot(), "attempt_id": self.attempt.get("attempt_id")}
        return {"browser": st, "session": snap, "attempt": self.attempt or None,
                "current_question": self.current, "last_answer": self.last_answer,
                "last_error": self.last_error, "mode": self.mode, "auto_submit": self.auto_submit,
                **det}

    def stop(self) -> dict:
        self.stopped.set()
        self.state.set(S.STOPPED, "stopped by user")
        try:
            self.browser.stop()
        except Exception:
            pass
        self._event("stop")
        return {"stopped": True, "state": self.state.snapshot()}

    def tabs(self) -> list[dict]:
        return self._ctrl("tabs", timeout=15)

    def switch_tab(self, index: int) -> dict:
        self._event("switch_tab", index=index)
        return self.browser.select_tab(index)

    def adopt_popup(self, timeout: float = 5.0) -> dict:
        return self._ctrl("adopt_popup", timeout=timeout + 10, timeout_s=timeout)

    def screenshot(self, full_page: bool = False) -> str:
        return self._ctrl("screenshot", timeout=30, full_page=full_page)

    # ------------------------------------------------------------------ detection
    def _probe_state(self) -> dict:
        det = self._ctrl("detection", timeout=90)
        self.detection = det
        pre_start = bool(det.get("start_control") and not det.get("question_count"))
        if det.get("ready_timeout") and not det.get("is_quiz"):
            self.state.set(S.BROWSER_READY, "page did not become ready in time")
        elif det.get("login_required"):
            self.state.set(S.AUTHENTICATION_REQUIRED, "login form visible - user must log in manually")
        elif pre_start:
            # an instruction page can mention "result"/"score" without the attempt being over:
            # a start control on a page with no questions outranks the results heuristic
            self.state.set(S.ATTEMPT_START_PENDING, "quiz page with a start control")
        elif det.get("results_page"):
            self.state.set(S.RESULTS_AVAILABLE, "results page")
        elif det.get("question_count"):
            self.current = det["current_question"]
            self.state.set(S.QUESTION_DETECTED if self.attempt.get("status") != "active" else S.QUESTION_DETECTED,
                           f"{det['question_count']} question(s) visible")
        elif det.get("is_quiz"):
            self.state.set(S.ATTEMPT_START_PENDING if det.get("start_control") else S.QUIZ_DETECTED,
                           "quiz page without visible questions")
        else:
            self.state.set(S.BROWSER_READY, "no quiz detected")
        return det

    def detect(self) -> dict:
        det = self._probe_state()
        self._event("detect", is_quiz=det.get("is_quiz"), questions=det.get("question_count"))
        return {"detection": det, "state": self.state.snapshot()}

    def current_question(self) -> dict:
        qs = self._ctrl("extract_questions", timeout=30)
        self.current = qs[0] if qs else None
        if self.current:
            self.state.set(S.QUESTION_DETECTED, "question read")
            if self.attempt.get("attempt_id"):
                self.store and self.store.upsert_question(self.attempt["attempt_id"], self.current)
        return {"found": bool(qs), "current": self.current, "questions": qs, "state": self.state.snapshot(),
                "error": None if qs else "no question found on the page"}

    # ------------------------------------------------------------------ attempt lifecycle
    def start_attempt(self) -> dict:
        pending = self.detection.get("start_control") and not self.detection.get("question_count")
        self.state.require(S.QUIZ_READY | {S.ATTEMPT_START_PENDING, S.QUESTION_DETECTED} |
                           ({S.RESULTS_AVAILABLE} if pending else set()), "start attempt")
        with self.state.operation("start attempt", S.ATTEMPT_START_PENDING):
            res = self._ctrl("start_attempt", timeout=60)
            if not res.get("started") and self._single_page_form():
                # a one-page quiz has no start control: opening it is the attempt
                res = {**res, "started": True, "single_page": True,
                       "reason": "one-page quiz: the open page is the attempt"}
            if res.get("started"):
                aid = f"att-{uuid.uuid4().hex[:10]}"
                det = self._ctrl("detection", timeout=90)
                self.attempt = {"attempt_id": aid, "status": "active", "url": self.browser.ctrl("status")["url"],
                                "title": det.get("quiz_title"), "total_questions": det.get("question_count"),
                                "site_attempt_id": res.get("site_attempt_id"), "started_at": time.time()}
                if self.store:
                    self.store.open_attempt(aid, self.state.session_id, self.attempt["url"], self.attempt["title"] or "")
                self.current = res.get("question")
                if self.current:
                    self.store and self.store.upsert_question(aid, self.current)
                self.state.set(S.ATTEMPT_ACTIVE, "attempt started")
            else:
                self.last_error = res.get("reason")
                # a refused start (e.g. disabled control) must stay retryable, not brick the session
                self.state.set(S.ATTEMPT_START_PENDING, res.get("reason"))
        self._event("attempt_start", started=res.get("started"), attempt_id=self.attempt.get("attempt_id"))
        return {**res, "attempt": self.attempt, "state": self.state.snapshot()}

    def _single_page_form(self) -> bool:
        try:
            det = self._ctrl("detection", timeout=90)
        except Exception:
            return False
        return (bool(det.get("is_quiz")) and not det.get("start_control")
                and not det.get("navigator_items") and not det.get("login_required"))

    def pause(self) -> dict:
        self.paused.set()
        prev = self.state.state
        if prev in {S.QUESTION_DETECTED, S.ANSWER_READY, S.ANSWER_SELECTED, S.ANSWER_SAVED, S.ATTEMPT_ACTIVE}:
            self.state.set(S.PAUSED, "paused by user")
        self._event("pause")
        return {"paused": True, "state": self.state.snapshot()}

    def resume(self) -> dict:
        self.paused.clear()
        if self.state.state == S.PAUSED:
            self.state.set(S.QUESTION_DETECTED if self.current else S.ATTEMPT_ACTIVE, "resumed")
        self._event("resume")
        return {"paused": False, "state": self.state.snapshot()}

    def stop_run(self) -> dict:
        self.stopped.set()
        self.paused.clear()
        # stopping does NOT click anything on the page: no accidental submission
        if self.state.state not in {S.SUBMITTED, S.RESULTS_AVAILABLE}:
            self.state.set(S.STOPPED, "run stopped by user (nothing submitted)")
        self._event("stop_run")
        return {"stopped": True, "submitted": False, "state": self.state.snapshot()}

    # ------------------------------------------------------------------ navigation
    def move(self, direction: str) -> dict:
        self.state.require(S.MOVE_ALLOWED, f"{direction} question")
        busy = S.MOVING_NEXT if direction == "next" else S.MOVING_PREVIOUS
        with self.state.operation(f"{direction} question", busy):
            res = self._ctrl("move_question", direction=direction)
            if res.get("ok"):
                self.current = res.get("question")
                self.state.set(S.QUESTION_DETECTED, "question changed")
                res["verified"] = True
                if self.attempt.get("attempt_id"):
                    self.store and self.store.upsert_question(self.attempt["attempt_id"], self.current)
            else:
                self.last_error = res.get("reason")
                self.state.set(S.QUESTION_DETECTED if res.get("before", {}).get("question_id")
                               else (S.ATTEMPT_ACTIVE if self.attempt.get("status") == "active" else S.ERROR),
                               res.get("reason") or "navigation failed")
        self._event(f"move_{direction}", ok=res.get("ok"), reason=res.get("reason"))
        return {**res, "state": self.state.snapshot()}

    def jump(self, index: int) -> dict:
        index = int(index)
        if index < 1:
            raise ValueError(f"question number must be >= 1, got {index}")
        self.state.require(S.QUIZ_READY, "jump to question")
        with self.state.operation("jump", S.MOVING_NEXT):
            res = self._ctrl("jump_to", index=index)
            if res.get("ok"):
                self.current = res.get("question")
                self.state.set(S.QUESTION_DETECTED, f"jumped to {index}")
            elif res.get("reason"):
                self.last_error = res.get("reason")
                self.state.set(S.QUESTION_DETECTED if res.get("question") else S.QUIZ_DETECTED, res["reason"])
            else:
                self.state.set(S.QUIZ_DETECTED, "jump returned no change")
        self._event("jump", index=index, ok=res.get("ok"), reason=res.get("reason"))
        return {**res, "state": self.state.snapshot()}

    def flag(self, question_id: str | None = None, flagged: bool = True) -> dict:
        qid = question_id or (self.current or {}).get("question_id")
        if not qid or not self.attempt.get("attempt_id"):
            return {"flagged": False, "reason": "no active attempt/question"}
        self.store and self.store.upsert_question(self.attempt["attempt_id"], self.current, flagged=int(flagged))
        self._event("flag", question_id=qid, flagged=flagged)
        return {"flagged": flagged, "question_id": qid, "review": self.review()}

    # ------------------------------------------------------------------ answering
    def answer(self, apply: bool = False, question: dict | None = None) -> dict:
        q = question or self.current
        if not q:
            got = self.current_question()
            q = got.get("current")
        if not q:
            return {"status": "needs_review", "error": "no question to answer", "state": self.state.snapshot()}
        self.state.require(S.QUIZ_READY, "answer")
        if question_ok := (q == self.current and self.state.state not in {S.PAUSED}):
            self.state.set(S.ANSWERING, "asking the model")
        self.current = q
        t0 = time.time()
        res = self.gateway.answer(q, attempt_id=self.attempt.get("attempt_id"))
        latency = res.get("latency_ms") or int((time.time() - t0) * 1000)
        self.last_answer = {**res, "question_id": q["question_id"], "applied": False, "saved": False,
                            "status": "proposed" if res.get("status") == "answered" else res.get("status")}
        if self.attempt.get("attempt_id") and self.store:
            self.store.upsert_question(self.attempt["attempt_id"], q, proposed=res, model_used=res.get("model_used"),
                                       provider_used=res.get("provider_used"), fallback_used=int(bool(res.get("fallback_used"))),
                                       latency_ms=latency, confidence=res.get("confidence"))
        if res.get("status") != "answered":
            self.last_error = res.get("error") or "model returned an uncertain answer"
            self.state.set(S.ANSWER_READY, "answer needs review")
        else:
            self.state.set(S.ANSWER_READY, "answer ready")
        self._event("answer", question_id=q["question_id"], model=res.get("model_used"), status=res.get("status"))
        answered = res.get("status") == "answered"
        out = dict(self.apply()) if (apply and answered) else {"applied": False,
                                                                "reason": "the model did not return a confident answer"}
        out["answer"] = self.last_answer
        out["state"] = self.state.snapshot()
        return out

    def _recorded_answer(self, question_id: str) -> list[str] | None:
        if not (self.store and self.attempt.get("attempt_id")):
            return None
        for rec in self.store.questions(self.attempt["attempt_id"]):
            if rec.get("question_id") == question_id and rec.get("applied"):
                sel = (rec.get("applied") or {}).get("selected_options")
                if sel:
                    return sorted(str(x) for x in sel)
        return None

    def apply(self, answer: dict | None = None) -> dict:
        ans = answer or self.last_answer
        if not ans or not self.current:
            return {"applied": False, "reason": "nothing to apply: no proposed answer for a current question"}
        if ans["question_id"] != self.current["question_id"]:
            return {"applied": False, "reason": "the proposed answer belongs to a different question"}
        recorded = self._recorded_answer(ans["question_id"])
        if recorded and recorded != sorted(str(x) for x in ans.get("selected_options") or []):
            return {"applied": False, "conflict": True, "recorded": recorded, "proposed": ans.get("selected_options"),
                    "reason": f"the attempt record already holds {recorded} for this question; not overwriting it"} 
        self.state.require(S.QUIZ_READY, "apply answer")
        with self.state.operation("apply answer", S.ANSWER_APPLYING):
            res = self.applier.apply(self.current["question_id"], ans)
            if res.get("conflict"):
                self.state.set(S.ANSWER_READY, res["reason"])
                self._record(saved_state="conflict")
                return {**res, "state": self.state.snapshot()}
            if res.get("applied"):
                self.state.set(S.ANSWER_SELECTED, "selection verified")
                self._record(applied=ans, saved_state="selected")
                self.last_answer = {**ans, "applied": True, "status": "applied", "observed": res.get("observed")}
            else:
                self.last_error = res.get("reason")
                self.state.set(S.ANSWER_READY, res.get("reason") or "apply failed")
        self._event("apply", applied=res.get("applied"), reason=res.get("reason"))
        return {**res, "state": self.state.snapshot()}

    def _record(self, **fields) -> None:
        if self.store and self.current and self.attempt.get("attempt_id"):
            self.store.upsert_question(self.attempt["attempt_id"], self.current, **fields)

    def save(self) -> dict:
        self.state.require(S.QUIZ_READY, "save answer")
        with self.state.operation("save answer", S.ANSWER_SAVING):
            res = self._ctrl("save_answer", timeout=45)
            kind = SaveManager.classify(res)
            selected = bool((self.last_answer or {}).get("applied"))
            # "saved" needs page evidence: either the site's save indicator or a verified selection
            res["saved"] = bool(res.get("saved") or (kind != "unsaved" and selected))
            if self.current and self.attempt.get("attempt_id"):
                self.store and self.store.upsert_question(
                    self.attempt["attempt_id"], self.current,
                    saved=bool(res.get("saved")) and selected or None,
                    saved_state=kind)
            self.state.set(S.ANSWER_SAVED if res.get("saved") else S.ANSWER_SELECTED,
                           "saved" if res.get("saved") else (res.get("reason") or "save state unknown"))
            if self.last_answer:
                self.last_answer = {**self.last_answer, "saved": bool(res.get("saved")),
                                    "status": "saved" if res.get("saved") else self.last_answer.get("status")}
        self._event("save", saved=res.get("saved"), indicator=res.get("indicator"))
        return {**res, "save_state": kind, "answer": self.last_answer, "state": self.state.snapshot()}

    def mark_verified(self, question_id: str, status: str, source: str = "user feedback") -> dict:
        if status not in {"correct", "incorrect"}:
            raise ValueError("status must be 'correct' or 'incorrect'")
        if not self.attempt.get("attempt_id"):
            return {"verified": False, "reason": "no active attempt"}
        q = next((r for r in (self.store.questions(self.attempt["attempt_id"]) if self.store else [])
                  if r["question_id"] == question_id), None)
        if self.store:
            self.store.upsert_question(self.attempt["attempt_id"], q or {"question_id": question_id},
                                       verified=status, verified_source=source)
        self._event("mark_verified", question_id=question_id, status=status, source=source)
        return {"verified": True, "question_id": question_id, "status": status, "source": source}

    # ------------------------------------------------------------------ review / progress
    def review(self) -> dict:
        records = self.store.questions(self.attempt["attempt_id"]) if (self.store and self.attempt.get("attempt_id")) else []
        qs = self._ctrl("extract_questions", timeout=30)
        answered = {r["question_id"] for r in records if r.get("applied") or r.get("saved")}
        return {
            "attempt": self.attempt or None,
            "questions": records,
            "answers": records,
            "visible": [{"question_index": q["question_index"], "question_id": q["question_id"],
                         "question_text": q["question_text"][:120], "answered_on_page": q["answered"]} for q in qs],
            "unanswered": [r["question_id"] for r in records if not (r.get("applied") or r.get("saved"))],
            "flagged": [r["question_id"] for r in records if r.get("flagged")],
            "conflicts": [r["question_id"] for r in records if r.get("saved_state") == "conflict"],
            "answered": sorted(answered),
            "state": self.state.snapshot(),
        }

    def progress(self) -> dict:
        ins = self._ctrl("inspect", timeout=20)
        qs = self._ctrl("extract_questions", timeout=30)
        records = self.store.questions(self.attempt["attempt_id"]) if (self.store and self.attempt.get("attempt_id")) else []
        answered = [r for r in records if r.get("applied") or r.get("saved")]
        unverified = [r["question_id"] for r in answered
                      if not (r.get("verified") or (r.get("saved_state") == "saved" and r.get("saved")))]
        return {"progress": ins.get("progress"), "timer": ins.get("timer"),
                "current": qs[0] if qs else None, "question_count": len(qs),
                "answered": sum(1 for q in qs if q.get("answered")),
                "recorded": len(answered), "unverified": unverified,
                "saved": sum(1 for r in records if r.get("saved")), "flagged": sum(1 for r in records if r.get("flagged")),
                "state": self.state.snapshot(), "attempt": self.attempt or None}

    # ------------------------------------------------------------------ submission
    def submit(self, confirm: bool = False, automated: bool = False) -> dict:
        if automated and not self.auto_submit:
            raise ValueError("automated submission is disabled: enable auto_submit for this session first")
        if not self.attempt.get("attempt_id"):
            return {"submitted": False, "reason": "no active attempt"}
        if self.attempt.get("status") == "submitted":
            return {"submitted": False, "duplicate": True, "already_submitted": True,
                    "reason": "this attempt is already submitted", "attempt": self.attempt}
        records = self.store.questions(self.attempt["attempt_id"]) if self.store else []
        self.state.require(S.QUIZ_READY | {S.SUBMISSION_PENDING}, "submit")
        with self.state.operation("submit", S.SUBMITTING):
            preview = self._ctrl("submission_preview", timeout=45, attempt=self.attempt, records=records)
            if not confirm:
                self.state.set(S.SUBMISSION_PENDING, "awaiting explicit confirmation")
                return {"submitted": False, "requires_confirmation": True, "preview": preview,
                        "state": self.state.snapshot()}
            res = self._ctrl("submit", timeout=120, confirm=True)
            if res.get("submitted"):
                self.attempt.update({"status": "submitted", "submitted_at": time.time()})
                result = res.get("result") or {}
                sc = (result or {}).get("score")
                fields = {"status": "submitted", "submitted_at": self.attempt["submitted_at"],
                          "result_source": result.get("source")}
                if sc:
                    fields.update({"score_earned": sc.get("earned"), "score_total": sc.get("total")})
                self.store and self.store.set_attempt(self.attempt["attempt_id"], **fields)
                self.state.set(S.RESULTS_AVAILABLE if sc else S.SUBMITTED,
                               "results captured" if sc else "submitted; result not released yet")
                res["results_pending"] = sc is None
            else:
                self.last_error = res.get("reason")
                self.state.set(S.SUBMISSION_PENDING, res.get("reason") or "submission not confirmed")
            res["preview"] = preview
        self._event("submit", submitted=res.get("submitted"))
        return {**res, "attempt": self.attempt, "state": self.state.snapshot()}

    def results(self) -> dict:
        rec = self.store.get_attempt(self.attempt["attempt_id"]) if (self.store and self.attempt.get("attempt_id")) else None
        if not rec:
            return {"submitted": False, "submitted_status": "no attempt", "score": None,
                    "note": "no attempt in this session"}
        from .metrics import compute_verified_metrics
        metrics = compute_verified_metrics(self.store.verified_records(rec["attempt_id"]))
        score = ({"earned": rec.get("score_earned"), "total": rec.get("score_total"),
                  "source": rec.get("result_source")} if rec.get("score_earned") is not None or rec.get("score_total") else None)
        return {"submitted": rec.get("status") == "submitted", "submitted_status": rec.get("status"),
                "attempt_id": rec["attempt_id"], "submitted_at": rec.get("submitted_at"),
                "score": score, "verified_metrics": metrics,
                "note": None if score else ("submitted; the site has not released a result" if rec.get("status") == "submitted" else "attempt not submitted")}

    # ------------------------------------------------------------------ automation loop
    def run_mode(self, mode: str, max_questions: int = 100) -> dict:
        """Assisted / practice automation. Stops at the review stage: submission only when
        auto_submit was explicitly enabled for this session."""
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}")
        if mode in {"observe", "assist"}:
            return {"started": False, "reason": f"mode {mode!r} is manual: use read/answer/apply controls"}
        self.mode = mode
        self.stopped.clear()
        self.paused.clear()
        out = {"mode": mode, "steps": [], "stopped": False}

        def worker():
            for _ in range(max_questions):
                if self.stopped.is_set():
                    out["stopped"] = True
                    return
                while self.paused.is_set() and not self.stopped.is_set():
                    time.sleep(0.3)
                try:
                    cur = self.current_question()
                    q = cur.get("current")
                    if not q:
                        out["steps"].append({"done": True, "reason": "no question visible (review/results page)"})
                        break
                    if q.get("answered") and not (self.last_answer or {}).get("applied"):
                        pass  # already answered on the page: still re-read and let the navigator move on
                    ans = self.answer(apply=(mode == "practice_automation"), question=q)
                    step = {"question_id": q["question_id"], "index": q.get("question_index"),
                            "status": (ans.get("answer") or {}).get("status"),
                            "applied": ans.get("applied")}
                    if ans.get("applied"):
                        step["save"] = self.save().get("save_state")
                    if (ans.get("answer") or {}).get("status") == "needs_review":
                        step["flagged"] = True
                        self.flag(q["question_id"], True)
                    out["steps"].append(step)
                    if self.stopped.is_set():
                        break
                    mv = self.move("next")
                    if not mv.get("ok"):
                        out["steps"].append({"done": True, "reason": mv.get("reason")})
                        break
                except S.StateConflict as e:
                    out["steps"].append({"error": str(e)})
                    break
                except Exception as e:
                    out["steps"].append({"error": f"{type(e).__name__}: {e}"})
                    break
            self.state.set(S.REVIEWING, "automation finished the question flow; review before submitting")

        self.runner = threading.Thread(target=worker, daemon=True, name="quizagent-run")
        self.runner.start()
        return {"started": True, "mode": mode, "state": self.state.snapshot()}


class _CtrlProxy:
    """Adapter so the navigator/applier helpers can use BrowserController-like calls from
    the HTTP thread (they all route through the Playwright thread)."""

    def __init__(self, sess: QuizSession):
        self.sess = sess

    def __getattr__(self, name):
        # the controller's parameters are (self, timeout) positionally, so the helper's first
        # positional argument can never be forwarded positionally: it would overwrite `timeout`.
        def call(*args, **kw):
            if args:
                raise TypeError(f"{name}() must pass its controller arguments by keyword")
            return self.sess._ctrl(name, **kw)
        return call


def _popup(sess: QuizSession) -> dict:
    return sess._ctrl("adopt_popup", timeout_s=5.0)
