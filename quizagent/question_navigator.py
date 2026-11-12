"""Question navigation and answer/form interaction, on top of BrowserController.

Every operation returns evidence: the question that actually appeared, the control state
that was actually read back. A click is never treated as proof."""
from __future__ import annotations

import re


class QuestionNavigator:
    def __init__(self, ctrl):
        self.ctrl = ctrl

    def next_question(self, timeout: float = 15.0) -> dict:
        return self.ctrl.move_question("next", timeout)

    def previous_question(self, timeout: float = 15.0) -> dict:
        return self.ctrl.move_question("previous", timeout)

    def jump(self, index: int) -> dict:
        return self.ctrl.jump_to(index)

    def jump_to_unanswered(self, records: list[dict]) -> dict:
        answered = {r["question_index"] for r in records if r.get("applied")}
        for q in self.ctrl.extract_questions():
            if not q.get("answered") and q.get("question_index") not in answered:
                return self.ctrl.jump_to(q["question_index"])
        return {"ok": False, "reason": "every visible question is answered"}

    def jump_to_flagged(self, records: list[dict]) -> dict:
        flagged = [r for r in records if r.get("flagged")]
        if not flagged:
            return {"ok": False, "reason": "no flagged question to jump to"}
        return self.ctrl.jump_to(flagged[0].get("question_index") or 1)

    def current(self) -> dict | None:
        return self.ctrl.current_question()


class AnswerApplier:
    """Applies a proposed answer to the real control, then confirms the resulting state."""

    def __init__(self, ctrl):
        self.ctrl = ctrl

    def apply(self, question_id: str, answer: dict) -> dict:
        found = self.ctrl.check_question_present(question_id=question_id) or {}
        visible = found.get("visible") or []
        if not found.get("present") or not found.get("question"):
            return {"applied": False, "reason": "expected question is no longer displayed", "conflict": True,
                    "visible_question_id": (visible[0]["question_id"] if visible else None)}
        q = found["question"]
        manual = self._manual_state(q)
        record_answer = answer.get("applied") or answer.get("selected_options") or answer.get("answer_text")
        if manual and record_answer and manual != self._normalize(answer):
            return {"applied": False, "conflict": True, "manual_state": manual, "recorded": self._normalize(answer),
                    "reason": "the page shows a different answer than the attempt record (manual edit) - not overwriting it"}
        res = self.ctrl.apply_answer(question=q, answer=answer) or {}
        observed = (res.get("verified") or {}).get("observed")
        return {**res, "question_id": question_id, "observed": observed,
                "verified": bool(res.get("applied")) and observed == self._normalize(answer)}

    def _manual_state(self, q: dict) -> list:
        if q.get("question_type") in {"short_answer", "long_answer"} and not q.get("options"):
            return [(q.get("text_value") or "").strip()] if (q.get("text_value") or "").strip() else []
        return sorted(str(o["id"]) for o in q.get("options") or [] if o.get("selected"))

    def _normalize(self, answer: dict) -> list:
        opts = [str(x) for x in answer.get("selected_options") or []]
        if opts:
            return sorted(opts)
        text = (answer.get("answer_text") or "").strip()
        return [text] if text else []


class SaveManager:
    """Records save state separately from selection state: selected is what the page shows,
    saved is only true when the page says so."""

    def __init__(self, ctrl):
        self.ctrl = ctrl

    def save(self) -> dict:
        return self.ctrl.save_answer()

    @staticmethod
    def classify(res: dict) -> str:
        if res.get("saved"):
            return "saved"
        ind = (res.get("indicator") or "").lower()
        if re.search(r"not (yet )?answered|unsaved|not saved", ind):
            return "unsaved"
        return "unknown"
