"""Unit tests for AI answering strategy, mock transport, confidence filtering, and review workflows."""
import unittest

from quizagent.ai_strategy import AIStrategy, MockTransport
from quizagent.model import Choice, Opt, Q
from quizagent.strategies import Chain


def make_q(kind: str, prompt: str, options: list[str]) -> Q:
    opts = [Opt(text=o, value=o) for o in options]
    return Q(kind=kind, prompt=prompt, options=opts, answered=False, mode="native", reliable=True, ctrl=None, frame=None)


class TestAIStrategy(unittest.TestCase):
    def test_mock_transport_answers_idempotent_question(self):
        strat = AIStrategy(provider="mock", mock=True, review_mode=False)
        q = make_q("single", "Which HTTP method is idempotent?", ["POST", "PUT", "PATCH", "CONNECT"])
        choice = strat.choose(q)
        self.assertTrue(choice.matched)
        self.assertIn("ai:", choice.source)
        # PUT option is at index 1
        self.assertIn(1, choice.indices)

    def test_mock_transport_answers_prime_numbers(self):
        strat = AIStrategy(provider="mock", mock=True, review_mode=False)
        q = make_q("multi", "Select all prime numbers.", ["2", "3", "4", "9"])
        choice = strat.choose(q)
        self.assertTrue(choice.matched)
        # 2 and 3 are at indices 0 and 1
        self.assertEqual(choice.indices, [0, 1])

    def test_mock_transport_answers_short_answer_text(self):
        strat = AIStrategy(provider="mock", mock=True, review_mode=False)
        q = make_q("text", "Chemical symbol for gold?", [])
        choice = strat.choose(q)
        self.assertTrue(choice.matched)
        self.assertEqual(choice.text, "Au")

    def test_review_callback_acceptance(self):
        called = []

        def review_accept(q_dict, ans):
            called.append((q_dict["question_id"], ans["selected_options"]))
            return Choice(indices=[0], source="user:accepted", matched=True)

        strat = AIStrategy(provider="mock", mock=True, review_mode=True, reviewer_fn=review_accept)
        q = make_q("single", "Capital of France?", ["Berlin", "Paris"])
        choice = strat.choose(q)

        self.assertEqual(len(called), 1)
        self.assertEqual(choice.source, "user:accepted")
        self.assertEqual(choice.indices, [0])

    def test_confidence_threshold_filtering(self):
        strat = AIStrategy(provider="mock", mock=True, review_mode=False, confidence_threshold=0.99)
        # Mock confidence is 0.95, which is < 0.99
        q = make_q("single", "Capital of France?", ["Berlin", "Paris"])
        choice = strat.choose(q)
        self.assertFalse(choice.matched)

    def test_chain_integration_with_ai_strategy(self):
        class DummyCache:
            enabled = False
            def get_answer(self, fp): return None

        strat = AIStrategy(provider="mock", mock=True, review_mode=False)
        import random
        chain = Chain(key=None, fallback="skip", rng=random.Random(0), cache=DummyCache(), ai_strategy=strat)

        q = make_q("single", "Which HTTP method is idempotent?", ["POST", "PUT", "PATCH"])
        choice = chain.choose(q)
        self.assertIsNotNone(choice)
        self.assertTrue(choice.matched)
        self.assertIn(1, choice.indices)


if __name__ == "__main__":
    unittest.main()
