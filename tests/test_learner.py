"""Unit tests for the Self-Learning Engine (DOM pattern learning and flow evolution)."""
import os
import tempfile
import unittest

from quizagent.adapters import LearnedAdapter, detect
from quizagent.learner import LearnedDOMPattern, SelfLearningEngine


class TestSelfLearningEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.learner = SelfLearningEngine(cache_dir=self.tmp.name)

    def tearDown(self):
        self.learner.close()
        import gc
        gc.collect()
        try:
            self.tmp.cleanup()
        except Exception:
            pass

    def test_learn_dom_structure_new_site(self):
        url = "https://eval.canvas.edu/courses/101/quizzes/5"
        observed = [
            {"kind": "single", "prompt": "Question 1"},
            {"kind": "multi", "prompt": "Question 2"},
            {"kind": "text", "prompt": "Question 3"},
        ]
        self.learner.learn_dom_structure(url, observed)

        pat = self.learner.get_learned_dom(url)
        self.assertIsNotNone(pat)
        self.assertIn("https://eval.canvas.edu/courses", pat.site_key)
        self.assertEqual(sorted(pat.input_kinds), ["multi", "single", "text"])
        self.assertGreaterEqual(pat.confidence, 0.5)

    def test_reinforcement_learning_increases_confidence(self):
        url = "https://testing.platform.org/exam/1"
        observed = [{"kind": "single", "prompt": "Q1"}]

        # First observation
        self.learner.learn_dom_structure(url, observed)
        pat1 = self.learner.get_learned_dom(url)

        # Repeated observations reinforce pattern
        for _ in range(5):
            self.learner.learn_dom_structure(url, observed)

        pat2 = self.learner.get_learned_dom(url)
        self.assertEqual(pat2.hits, 6)
        self.assertGreater(pat2.confidence, pat1.confidence)

    def test_flow_transition_recording_and_best_action(self):
        url = "https://custom-spa.net/quiz/start"
        self.learner.record_transition(url, "landing", "start", "#btn-start-quiz", "questions", success=True)
        self.learner.record_transition(url, "questions", "next", ".nav-next", "questions", success=True)
        self.learner.record_transition(url, "questions", "submit", "#finish-attempt", "summary", success=True)
        self.learner.record_transition(url, "summary", "confirm", ".modal-confirm-btn", "done", is_modal=True, success=True)

        best_start = self.learner.get_best_flow_action(url, "landing")
        self.assertIsNotNone(best_start)
        self.assertEqual(best_start["action_selector"], "#btn-start-quiz")
        self.assertEqual(best_start["to_phase"], "questions")

        best_summary = self.learner.get_best_flow_action(url, "summary")
        self.assertIsNotNone(best_summary)
        self.assertEqual(best_summary["action_selector"], ".modal-confirm-btn")
        self.assertTrue(bool(best_summary["is_modal"]))

    def test_results_markers_learning(self):
        url = "https://testing.platform.org/exam/1"
        res_text = "Assessment finished! Your final grade: 9 / 10 marks obtained."
        self.learner.learn_results_markers(url, res_text)

        stats = self.learner.stats()
        self.assertGreaterEqual(stats["learned_indicators"], 1)

    def test_learned_adapter_generation_and_detect_integration(self):
        url = "https://unique-spa.io/assessment/take"
        self.learner.learn_dom_structure(url, [{"kind": "single"}])
        # Artificially set high confidence
        key = self.learner.site_key(url)
        self.learner.db.execute("update learned_dom_patterns set confidence=0.85 where site_key=?", (key,))
        self.learner.db.commit()

        class DummyPage:
            url = "https://unique-spa.io/assessment/take"
            def evaluate(self, js): return False

        adapter = detect(DummyPage(), learner=self.learner)
        self.assertTrue(isinstance(adapter, LearnedAdapter))
        self.assertIn("learned:", adapter.name)

    def test_stats_and_clear(self):
        url = "https://moodle.test/mod/quiz"
        self.learner.learn_dom_structure(url, [{"kind": "single"}])
        self.learner.record_transition(url, "start", "next", "btn", "questions")

        stats = self.learner.stats()
        self.assertEqual(stats["learned_sites"], 1)
        self.assertEqual(stats["learned_transitions"], 1)

        self.learner.clear()
        stats_after = self.learner.stats()
        self.assertEqual(stats_after["learned_sites"], 0)
        self.assertEqual(stats_after["learned_transitions"], 0)


if __name__ == "__main__":
    unittest.main()
