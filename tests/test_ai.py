"""Model routing, provider adapters, fallback, malformed output, image requirements, missing keys."""
import json
import os
import unittest
from unittest import mock

from quizagent.llm import MODELS, capabilities_summary, candidates_for, missing_keys, provider_chain, task_map
from quizagent.llm.gateway import Gateway, ProviderError, _classify_error
from quizagent.llm.task_classifier import classify_task


class FakeResponse:
    def __init__(self, payload=None, status=200, body=""):
        self.payload, self.status, self.body = payload, status, body


def transport_ok(content):
    calls = []

    def t(spec, payload, key, timeout):
        calls.append((spec.logical_name, payload))
        return {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    t.calls = calls
    return t


Q = {"question_id": "q1", "question_text": "Capital of France?", "question_type": "single_choice",
     "options": [{"id": "A", "text": "Berlin"}, {"id": "B", "text": "Paris"}]}


class TestRouting(unittest.TestCase):
    def test_every_configured_task_routes_to_a_known_model(self):
        for task, mapping in task_map().items():
            self.assertEqual(mapping["primary"], mapping["chain"][0], task)
            for slug in mapping["chain"]:
                self.assertIn(slug, MODELS, task)

    def test_task_table_matches_spec(self):
        tm = task_map()
        self.assertEqual(tm["reasoning"]["primary"], "nemotron_ultra")
        self.assertIn("nemotron_lightning", tm["reasoning"]["chain"])
        self.assertEqual(tm["vision"]["primary"], "nemotron_super_vl")
        self.assertIn("gemma_4", tm["vision"]["chain"])
        self.assertEqual(tm["code"]["primary"], "north_mini_code")
        self.assertIn("nemotron_ultra", tm["code"]["chain"])
        self.assertEqual(tm["multimodal"]["primary"], "nemotron_super_vl")
        self.assertIn("nemotron_nano_omni", tm["multimodal"]["chain"])

    def test_vision_chain_has_no_text_only_model(self):
        for slug in task_map()["vision"]["chain"]:
            self.assertTrue({"vision", "image", "multimodal"} & MODELS[slug].capabilities, slug)
        for slug in task_map()["multimodal"]["chain"]:
            self.assertTrue({"vision", "image", "multimodal"} & MODELS[slug].capabilities, slug)

    def test_image_question_never_routed_to_text_only_model(self):
        for spec in candidates_for("vision", needs_image=True):
            self.assertTrue({"vision", "image", "multimodal"} & spec.capabilities, spec.logical_name)
        self.assertNotIn("nemotron_lightning", [s.logical_name for s in candidates_for("vision", needs_image=True)])

    def test_provider_chain_starts_with_primary_and_skips_capability_mismatch(self):
        chain = provider_chain("nemotron_ultra", "reasoning")
        self.assertEqual(chain[0].logical_name, "nemotron_ultra")
        self.assertTrue(any(s.provider == "openrouter" for s in chain))
        img = provider_chain("nemotron_super_vl", "vision", needs_image=True)
        self.assertTrue(all({"vision", "image", "multimodal"} & s.capabilities for s in img))

    def test_classifier(self):
        self.assertEqual(classify_task({**Q, "images": ["a.png"]}), "vision")
        self.assertEqual(classify_task({**Q, "question_text": "What does this code print?\n```py\nprint(1)\n```"}), "code")
        self.assertEqual(classify_task(Q), "general")
        self.assertEqual(classify_task({**Q, "question_text": "Explain in detail why " + "x" * 500}), "reasoning")


class TestGateway(unittest.TestCase):
    def gw(self, transport, keys=("NVIDIA_API_KEY", "OPENROUTER_API_KEY")):
        env = {k: "k" for k in keys}
        return Gateway(transport=transport, key_lookup=env.get, max_retries=0, sleep=lambda s: None)

    def test_nvidia_answer_normalised(self):
        body = json.dumps({"selected_options": ["B"], "explanation": "Paris", "confidence": 0.9, "status": "answered"})
        out = self.gw(transport_ok(body)).answer(Q, primary="nemotron_ultra")
        self.assertEqual(out["selected_options"], ["B"])
        self.assertEqual(out["model_used"], "nemotron_ultra")
        self.assertEqual(out["provider_used"], "nvidia")
        self.assertEqual(out["status"], "answered")
        self.assertFalse(out["fallback_used"])

    def test_openrouter_adapter(self):
        body = json.dumps({"selected_options": ["A"], "confidence": 0.4})
        t = transport_ok(body)
        out = self.gw(t).answer(Q, primary="nemotron_ultra_or")
        self.assertEqual(out["provider_used"], "openrouter")
        self.assertEqual(MODELS["nemotron_ultra_or"].model_id, "nvidia/nemotron-3-ultra-550b-a55b:free")
        self.assertTrue(t.calls[0][1]["model"].endswith(":free"))

    def test_primary_failure_falls_back(self):
        def transport(spec, payload, key, timeout):
            if spec.provider == "nvidia":
                raise ProviderError("provider", "boom", 503)
            return {"choices": [{"message": {"content": json.dumps({"selected_options": ["B"], "status": "answered"})}}]}
        out = self.gw(transport).answer(Q, primary="nemotron_ultra")
        self.assertTrue(out["fallback_used"])
        self.assertEqual(out["provider_used"], "openrouter")

    def test_malformed_json_is_needs_review_not_a_crash(self):
        out = self.gw(transport_ok("the answer is Paris")).answer(Q, primary="nemotron_ultra")
        self.assertEqual(out["status"], "needs_review")
        self.assertTrue(out["needs_review"])
        self.assertIsNone(out["model_used"])
        self.assertIn("malformed_json", out["error"])

    def test_invalid_option_id_never_returns_an_option_that_does_not_exist(self):
        body = json.dumps({"selected_options": ["Paris", "Z"], "status": "answered", "confidence": 0.9})
        out = self.gw(transport_ok(body)).answer(Q, primary="nemotron_ultra")
        self.assertEqual(out["selected_options"], ["B"])
        self.assertEqual(out["discarded_invalid_options"], ["Z"])
        self.assertEqual(out["status"], "needs_review")
        self.assertTrue(all(o in {"A", "B"} for o in out["selected_options"]))

    def test_missing_provider_keys(self):
        out = Gateway(transport=transport_ok("{}"), key_lookup=lambda e: None).answer(Q, primary="nemotron_ultra")
        self.assertEqual(out["status"], "needs_review")
        self.assertIn("missing NVIDIA_API_KEY", out["error"])
        self.assertIn("missing OPENROUTER_API_KEY", out["error"])

    def test_missing_keys_helper(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(set(missing_keys()), {"NVIDIA_API_KEY", "OPENROUTER_API_KEY"})

    def test_image_question_payload_is_multimodal(self):
        t = transport_ok(json.dumps({"status": "uncertain"}))
        q = {**Q, "images": ["https://x/y.png"], "question_type": "image"}
        self.gw(t).answer(q)
        used = t.calls[0][0]
        self.assertIn(MODELS[used].logical_name, {"nemotron_super_vl", "nemotron_super_vl_or", "gemma_4", "nemotron_nano_omni"})
        self.assertIsInstance(t.calls[0][1]["messages"][-1]["content"], list)

    def test_error_classification(self):
        import urllib.error
        self.assertEqual(_classify_error(urllib.error.HTTPError("u", 401, "x", {}, None)).kind, "auth")
        self.assertEqual(_classify_error(urllib.error.HTTPError("u", 429, "x", {}, None)).kind, "rate_limit")
        self.assertEqual(_classify_error(json.JSONDecodeError("x", "y", 0)).kind, "malformed_json")

    def test_rate_limit_retries_bounded(self):
        import urllib.error
        calls = []
        sleeps = []

        def transport(spec, payload, key, timeout):
            calls.append(spec.logical_name)
            raise urllib.error.HTTPError("u", 429, "slow down", {}, None)
        gw = Gateway(transport=transport, key_lookup=lambda e: "k", max_retries=1, sleep=sleeps.append)
        out = gw.answer(Q, primary="nemotron_ultra")
        self.assertEqual(out["status"], "needs_review")
        self.assertLessEqual(len(calls), 2 * len(provider_chain("nemotron_ultra", "general")))
        self.assertTrue(all(s >= 2.0 for s in sleeps))

    def test_capabilities_endpoint_shape(self):
        caps = capabilities_summary()
        self.assertIn("vision", caps["nemotron_super_vl"]["capabilities"])
        self.assertEqual(caps["north_mini_code"]["provider"], "openrouter")


if __name__ == "__main__":
    unittest.main()
