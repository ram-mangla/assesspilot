"""HTTP surface: token auth, state conflicts, submission confirmation, metrics."""
import os
import tempfile
import unittest

from quizagent import session_state as S
from quizagent.server import create_app
from quizagent.store import Store
from tests.fakes import FakeBrowser, mkq


class FakeGateway:
    def answer(self, question, **kw):
        return {"selected_options": ["B"], "answer_text": "", "explanation": "", "confidence": 0.9,
                "status": "answered", "model_used": "nemotron_ultra", "provider_used": "nvidia",
                "needs_review": False, "fallback_used": False}


class TestServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "facts.db"))
        self.browser = FakeBrowser()
        app = create_app(self.store, browser_factory=lambda: self.browser, gateway=FakeGateway(), token="tok")
        self.client = app.test_client()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def post(self, path, **body):
        return self.client.post(f"{path}?t=tok", json=body)

    def test_missing_token_is_403(self):
        self.assertEqual(self.client.get("/quiz/detect").status_code, 405)
        self.assertEqual(self.client.post("/quiz/detect", json={}).status_code, 403)

    def test_header_token_accepted(self):
        r = self.client.get("/ai/models", headers={"X-Quiz-Token": "tok"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("models", r.get_json())

    def test_start_then_status(self):
        r = self.post("/browser/session/start", url="https://quiz.test/q")
        self.assertEqual(r.status_code, 200)
        s = self.client.get("/browser/session/status?t=tok").get_json()
        self.assertIn(s["session"]["state"], S.QUIZ_READY)
        self.assertTrue(s["request_id"])

    def test_conflict_maps_to_409_with_kind(self):
        r = self.post("/quiz/question/next")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["kind"], "state_conflict")

    def test_missing_url_is_400(self):
        self.assertEqual(self.post("/browser/session/start").status_code, 400)

    def test_submit_needs_confirm_flag(self):
        self.post("/browser/session/start", url="https://quiz.test/q")
        self.post("/quiz/attempt/start")
        preview = self.post("/quiz/attempt/submit", confirm=False).get_json()
        self.assertTrue(preview["requires_confirmation"])
        done = self.post("/quiz/attempt/submit", confirm=True).get_json()
        self.assertTrue(done["submitted"])
        again = self.post("/quiz/attempt/submit", confirm=True).get_json()
        self.assertFalse(again["submitted"])

    def test_metrics_endpoint_without_results(self):
        m = self.client.get("/metrics/summary?t=tok").get_json()
        self.assertEqual(m["verified"]["display"], "No verified results yet")
        self.assertIsNone(m["verified"]["success_rate"])

    def test_answer_and_flag_routes(self):
        self.post("/browser/session/start", url="https://quiz.test/q")
        self.post("/quiz/attempt/start")
        a = self.post("/quiz/answer", apply=True).get_json()
        self.assertEqual(a["answer"]["status"], "applied")
        f = self.post("/quiz/question/flag", flagged=True).get_json()
        self.assertTrue(f["flagged"])

    def test_dashboard_served_with_token(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("__TOKEN__", r.get_data(as_text=True))
        self.assertIn("tok", r.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
