"""Verified-only success rate: nothing unverified may move the number."""
import unittest

from quizagent.metrics import by_model, compute_verified_metrics, success_rate


def rec(qid, status, attempt="a1", model="nemotron_ultra", provider="nvidia", task="reasoning"):
    return {"attempt_id": attempt, "question_id": qid, "verified_status": status,
            "model_used": model, "provider_used": provider, "task": task}


class TestSuccessRate(unittest.TestCase):
    def test_no_verified_results_returns_none(self):
        m = compute_verified_metrics([])
        self.assertIsNone(m["success_rate"])
        self.assertEqual(m["display"], "No verified results yet")
        self.assertEqual(m["note"], "No verified results yet")

    def test_eight_correct_two_incorrect_is_80(self):
        m = compute_verified_metrics([rec(f"q{i}", "correct") for i in range(8)] + [rec("x", "incorrect"), rec("y", "incorrect")])
        self.assertEqual(m["success_rate"], 80.0)
        self.assertEqual((m["verified_correct"], m["verified_incorrect"]), (8, 2))

    def test_unverified_skipped_failed_unanswered_excluded(self):
        records = [rec("q1", "correct"), rec("q2", "skipped"), rec("q3", "failed"),
                   rec("q4", "unanswered"), rec("q5", "needs_review"), rec("q6", "")]
        m = compute_verified_metrics(records)
        self.assertEqual(m["verified_total"], 1)
        self.assertEqual(m["success_rate"], 100.0)

    def test_regrade_not_double_counted(self):
        records = [rec("q1", "incorrect"), rec("q1", "correct"), rec("q2", "correct")]
        m = compute_verified_metrics(records)
        self.assertEqual(m["verified_total"], 2)
        self.assertEqual(m["success_rate"], 100.0)

    def test_confidence_does_not_affect_correctness(self):
        records = [{**rec("q1", "incorrect"), "confidence": 0.99}, {**rec("q2", "correct"), "confidence": 0.01}]
        m = compute_verified_metrics(records)
        self.assertEqual(m["success_rate"], 50.0)

    def test_not_hardcoded_95(self):
        self.assertNotEqual(success_rate(0, 1), 95)
        self.assertIsNone(success_rate(0, 0))

    def test_by_model_buckets(self):
        out = by_model([rec("q1", "correct", model="a"), rec("q2", "incorrect", model="a"),
                        rec("q3", "correct", model="b", provider="openrouter")])
        self.assertEqual(out["a|nvidia|reasoning"]["correct"], 1)
        self.assertEqual(out["b|openrouter|reasoning"]["success_rate"], 100.0)


if __name__ == "__main__":
    unittest.main()
