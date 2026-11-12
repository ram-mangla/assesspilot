"""State machine, navigation verification, answer lifecycle and submission safety (no browser)."""
import json
import os
import tempfile
import unittest

from quizagent import session_state as S
from quizagent.quiz_session import QuizSession
from quizagent.store import Store
from tests.fakes import FakeBrowser, StubController, mkq


class FakeGateway:
    def __init__(self, answer=None):
        self.answer_out = answer or {"selected_options": ["B"], "answer_text": "", "explanation": "Paris",
                                     "confidence": 0.8, "status": "answered", "model_used": "nemotron_ultra",
                                     "provider_used": "nvidia", "needs_review": False, "fallback_used": False}
        self.calls = 0

    def answer(self, question, **kw):
        self.calls += 1
        return dict(self.answer_out)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "cache"))
        self.ctrl = StubController(questions=[
            mkq("q1", "Capital of France?", index=1),
            mkq("q2", "Pick two", options=("A", "B", "C", "D"), qtype="multi_choice", index=2),
            mkq("q3", "Explain", options=("A", "B"), qtype="short_answer", index=3)])
        self.browser = FakeBrowser(self.ctrl)
        self.gw = FakeGateway()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def qs(self, **kw):
        return QuizSession(self.browser, store=self.store, gateway=self.gw, **kw)

    def started(self, **kw):
        q = self.qs(**kw)
        q.start("https://quiz.test/q")
        q.start_attempt()
        return q


class TestStateMachine(Base):
    def test_initial_state_is_idle(self):
        q = self.qs()
        self.assertEqual(q.status()["session"]["state"], S.IDLE)

    def test_navigation_before_open_conflicts(self):
        q = self.qs()
        with self.assertRaises(S.StateConflict):
            q.move("next")

    def test_start_sets_quiz_ready_and_records_attempt(self):
        q = self.started()
        self.assertIn(q.status()["session"]["state"], S.QUIZ_READY)
        self.assertTrue(self.store.get_attempt(q.status()["session"]["attempt_id"]))

    def test_instruction_page_with_start_control_is_not_results(self):
        # a real instruction page mentioned "result"/"score": results_page must not block the start
        self.ctrl.questions = []
        self.ctrl.results_page = True
        q = self.qs()
        q.start("https://quiz.test/q")
        self.assertEqual(q.status()["session"]["state"], S.ATTEMPT_START_PENDING)
        q.start_attempt()
        self.assertIn(q.status()["session"]["state"], S.QUIZ_READY)

    def test_pause_blocks_navigation_resume_restores(self):
        q = self.started()
        q.pause()
        with self.assertRaises(S.StateConflict):
            q.move("next")
        q.resume()
        self.assertTrue(q.move("next")["ok"])

    def test_stop_never_clicks_submit(self):
        q = self.started()
        q.stop_run()
        self.assertNotIn("submit", [c[0] for c in self.ctrl.calls])
        self.assertEqual(q.status()["session"]["state"], S.STOPPED)


class TestNavigation(Base):
    def test_next_verifies_question_changed(self):
        q = self.started()
        out = q.move("next")
        self.assertTrue(out["ok"])
        self.assertEqual(out["question"]["question_id"], "q2")
        self.assertTrue(out["verified"])

    def test_next_past_last_question_reports_failure(self):
        q = self.started()
        q.jump(3)
        out = q.move("next")
        self.assertFalse(out["ok"])
        self.assertIn("reason", out)

    def test_jump_out_of_range_rejected(self):
        q = self.started()
        with self.assertRaises(ValueError):
            q.jump(0)

    def test_previous_at_first_question_does_not_claim_success(self):
        q = self.started()
        self.assertFalse(q.move("previous")["ok"])

    def test_navigation_keeps_recorded_answer(self):
        q = self.started()
        q.answer(apply=True)
        q.move("next")
        q.jump(1)
        recs = self.store.questions(q.status()["session"]["attempt_id"])
        self.assertEqual(recs[0]["proposed"]["selected_options"], ["B"])


class TestAnswerLifecycle(Base):
    def test_answer_is_proposed_not_applied(self):
        q = self.started()
        out = q.answer(apply=False)
        self.assertEqual(out["answer"]["status"], "proposed")
        self.assertNotIn("apply", [c[0] for c in self.ctrl.calls])

    def test_apply_then_save_transitions(self):
        q = self.started()
        q.answer(apply=True)
        self.assertEqual(q.status()["last_answer"]["status"], "applied")
        self.ctrl.saved_indicator = "Answer saved"
        out = q.save()
        self.assertTrue(out["saved"])
        self.assertEqual(out["answer"]["status"], "saved")

    def test_unsaved_answer_is_reported_as_unsaved(self):
        q = self.started()
        q.answer(apply=True)
        out = q.save()
        self.assertFalse(out["saved"])
        self.assertEqual(out["answer"]["status"], "applied")

    def test_multi_choice_uses_exact_option_ids(self):
        q = self.started()
        q.jump(2)
        self.gw.answer_out = {"selected_options": ["A", "C"], "status": "answered", "confidence": 0.7,
                              "answer_text": "", "explanation": "", "model_used": "m", "provider_used": "nvidia",
                              "needs_review": False, "fallback_used": False}
        out = q.answer(apply=True)
        self.assertTrue(out["applied"])
        sel = [o["id"] for o in self.ctrl.questions[1]["options"] if o["selected"]]
        self.assertEqual(sel, ["A", "C"])

    def test_conflict_is_detected_not_overwritten(self):
        q = self.started()
        self.store.upsert_question(q.status()["session"]["attempt_id"], {"question_id": "q1"},
                                   applied={"selected_options": ["A"]}, applied_at="2024-01-01T00:00:00")
        self.gw.answer_out = {**self.gw.answer_out, "selected_options": ["B"]}
        q.answer()
        out = q.apply()
        self.assertFalse(out["applied"])
        self.assertIn("conflict", json.dumps(out).lower())

    def test_needs_review_answer_is_never_applied(self):
        q = self.started()
        self.gw.answer_out = {"selected_options": [], "status": "needs_review", "error": "provider down",
                              "confidence": 0.0, "answer_text": "", "explanation": "", "model_used": None,
                              "provider_used": None, "needs_review": True, "fallback_used": False}
        out = q.answer(apply=True)
        self.assertFalse(out["applied"])
        self.assertNotIn("apply", [c[0] for c in self.ctrl.calls])

    def test_review_and_progress(self):
        q = self.started()
        q.answer(apply=True)
        self.assertEqual(q.review()["answers"][0]["question_id"], "q1")
        p = q.progress()
        self.assertEqual(p["answered"], 1)
        self.assertIn("unverified", p)


class TestSubmission(Base):
    def test_preview_does_not_submit(self):
        q = self.started()
        q.answer(apply=True)
        prev = q.submit(confirm=False)
        self.assertTrue(prev["requires_confirmation"])
        self.assertNotIn("submit", [c[0] for c in self.ctrl.calls])

    def test_confirm_submits_and_captures_results(self):
        q = self.started()
        out = q.submit(confirm=True)
        self.assertTrue(out["submitted"])
        self.assertEqual(out["result"]["score"]["pct"], 70.0)
        self.assertEqual(self.store.get_attempt(q.status()["session"]["attempt_id"])["status"], "submitted")

    def test_duplicate_submit_is_rejected(self):
        q = self.started()
        q.submit(confirm=True)
        second = q.submit(confirm=True)
        self.assertFalse(second["submitted"])
        self.assertTrue(second["already_submitted"])
        self.assertEqual(self.ctrl.confirmations, [True])

    def test_results_pending_after_submit_without_score(self):
        self.ctrl.score_text = "Submitted. Your results are pending."
        q = self.started()
        out = q.submit(confirm=True)
        self.assertTrue(out["submitted"])
        self.assertIsNone(out["result"]["score"])
        self.assertEqual(q.results()["score"], None)

    def test_auto_submit_refused_when_disabled(self):
        q = self.started()
        with self.assertRaises(ValueError):
            q.submit(confirm=True, automated=True)


if __name__ == "__main__":
    unittest.main()
