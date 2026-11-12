"""AI-powered answering strategy for QuizAgent.

Integrates the multi-model LLM gateway with the browser agent, supporting NVIDIA NIM,
OpenRouter, and mock providers, with human-in-the-loop review mode.
"""
from __future__ import annotations

import logging
import re
import sys
from typing import Any, Callable, Dict, List, Optional

from .llm import MODELS
from .llm.gateway import Gateway
from .model import Choice, Opt, Q
from .normalize import norm_opt

logger = logging.getLogger("quizagent.ai_strategy")


class MockTransport:
    """Mock transport providing deterministic responses for offline testing and demos."""

    def __call__(self, spec, payload: dict, key: str, timeout: float) -> dict:
        messages = payload.get("messages", [])
        content = messages[-1].get("content", "") if messages else ""

        # Deterministic parsing of question prompt to provide high-quality simulated answers
        prompt_lower = content.lower() if isinstance(content, str) else str(content).lower()

        selected = ["A"]
        text = "42"
        confidence = 0.95
        explanation = f"Simulated analysis from {spec.logical_name}"

        if "idempotent" in prompt_lower:
            # PUT option
            selected = ["B"] if "put" in prompt_lower else ["A"]
            explanation = "PUT is idempotent because multiple identical requests produce the same result."
        elif "prime" in prompt_lower:
            selected = ["A", "B"]  # 2 and 3
            explanation = "2 and 3 are prime numbers; 4 and 9 are composite."
        elif "handshake" in prompt_lower or "three packets" in prompt_lower:
            selected = ["A"]  # True
            explanation = "The standard TCP connection establishment uses a three-way handshake (SYN, SYN-ACK, ACK)."
        elif "france" in prompt_lower or "paris" in prompt_lower:
            selected = ["B"]
            text = "Paris"
            explanation = "Paris is the capital of France."
        elif "gold" in prompt_lower or "symbol" in prompt_lower:
            text = "Au"
            selected = ["A"]
            explanation = "The chemical symbol for gold is Au (from Latin aurum)."
        elif "7 x 6" in prompt_lower or "42" in prompt_lower:
            text = "42"
            explanation = "7 multiplied by 6 equals 42."
        elif "not found" in prompt_lower or "status code" in prompt_lower:
            text = "404"
            explanation = "HTTP 404 Not Found indicates that the origin server did not find the requested resource."

        ans_payload = {
            "selected_options": selected,
            "answer_text": text,
            "confidence": confidence,
            "explanation": explanation,
            "status": "answered",
        }

        import json
        return {
            "choices": [{"message": {"content": json.dumps(ans_payload)}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 40},
        }


class AIStrategy:
    """Answer strategy leveraging LLM models with human review support."""

    def __init__(
        self,
        provider: str = "nvidia",
        model: Optional[str] = None,
        review_mode: bool = True,
        confidence_threshold: float = 0.6,
        gateway: Optional[Gateway] = None,
        mock: bool = False,
        reviewer_fn: Optional[Callable[[dict, dict], Optional[Choice]]] = None,
    ):
        self.provider = provider
        self.model = model or ("nemotron_ultra" if provider == "nvidia" else "nemotron_ultra_or")
        self.review_mode = review_mode
        self.confidence_threshold = confidence_threshold
        self.mock = mock
        self.reviewer_fn = reviewer_fn

        if gateway:
            self.gateway = gateway
        elif mock:
            self.gateway = Gateway(transport=MockTransport(), key_lookup=lambda k: "mock-key", max_retries=0)
        else:
            self.gateway = Gateway()

    def _build_payload(self, q: Q) -> dict:
        """Convert internal Q model to Gateway question schema."""
        qtype_map = {
            "single": "single_choice",
            "multi": "multiple_choice",
            "select": "single_choice",
            "text": "short_answer",
            "textarea": "long_answer",
            "number": "short_answer",
        }
        qtype = qtype_map.get(q.kind, "short_answer")
        opts = [{"id": chr(65 + i), "text": o.text} for i, o in enumerate(q.options)]

        return {
            "question_id": q.key,
            "question_text": q.prompt,
            "question_type": qtype,
            "options": opts,
            "images": [],
        }

    def choose(self, q: Q) -> Choice:
        """Evaluate the question with the configured AI model and return a Choice."""
        q_dict = self._build_payload(q)

        try:
            ans = self.gateway.answer(q_dict, primary=self.model)
        except Exception as e:
            logger.warning("AI gateway query failed: %s", e)
            return Choice(matched=False)

        if ans.get("error") and not ans.get("selected_options") and not ans.get("answer_text"):
            logger.info("AI model returned error: %s", ans.get("error"))
            return Choice(matched=False)

        # In review mode, consult reviewer
        if self.review_mode:
            if self.reviewer_fn:
                user_choice = self.reviewer_fn(q_dict, ans)
                if user_choice is not None:
                    return user_choice
            else:
                user_choice = self._default_cli_review(q, q_dict, ans)
                if user_choice is not None:
                    return user_choice

        # Automatic acceptance if confidence exceeds threshold
        conf = float(ans.get("confidence") or 0.0)
        if conf < self.confidence_threshold:
            logger.info("Confidence %.2f below threshold %.2f, skipping AI answer", conf, self.confidence_threshold)
            return Choice(matched=False)

        return self._format_choice(q, ans)

    def _format_choice(self, q: Q, ans: dict) -> Choice:
        """Map Gateway answer output back into internal Choice indices/text."""
        model_name = ans.get("model_used") or self.model
        source = f"ai:{model_name}"

        if q.kind in ("text", "textarea", "number"):
            text_val = ans.get("answer_text") or (ans.get("selected_options") or [""])[0]
            return Choice(text=str(text_val), source=source, matched=True)

        selected_ids = ans.get("selected_options") or []
        indices: List[int] = []

        for want in selected_ids:
            want_str = str(want).strip().upper()
            # If letter A, B, C...
            if len(want_str) == 1 and "A" <= want_str <= "Z":
                idx = ord(want_str) - ord("A")
                if 0 <= idx < len(q.options):
                    indices.append(idx)
                    continue

            # Text match
            for i, opt in enumerate(q.options):
                if norm_opt(opt.text) == norm_opt(want_str) or want_str in norm_opt(opt.text):
                    indices.append(i)
                    break

        if not indices and q.options:
            return Choice(matched=False)

        return Choice(indices=sorted(set(indices)), source=source, matched=True)

    def _default_cli_review(self, q: Q, q_dict: dict, ans: dict) -> Optional[Choice]:
        """Interactive terminal review prompt for user-in-the-loop assistance."""
        if not sys.stdin.isatty():
            # Non-interactive terminal: auto-accept if confidence is acceptable
            return self._format_choice(q, ans)

        print("\n" + "=" * 65)
        print(f" [AI QUESTION REVIEW]  Question: {q.prompt}")
        print("-" * 65)

        for i, opt in enumerate(q.options):
            marker = chr(65 + i)
            is_suggested = marker in (ans.get("selected_options") or [])
            star = " [*]" if is_suggested else "    "
            print(f"  {star} ({marker}) {opt.text}")

        if q.kind in ("text", "textarea", "number"):
            print(f"   Suggested Text: \"{ans.get('answer_text')}\"")

        model_name = ans.get("model_used") or self.model
        conf_pct = int((ans.get("confidence") or 0.0) * 100)
        print(f"\n Model: {model_name} | Confidence: {conf_pct}%")
        if ans.get("explanation"):
            print(f" Reasoning: {ans.get('explanation')}")
        print("=" * 65)

        try:
            prompt = "Action [Y=accept, N=skip, E=edit, F=fallback]: "
            choice = input(prompt).strip().lower()
            if choice in ("y", "yes", ""):
                return self._format_choice(q, ans)
            if choice in ("n", "no"):
                return Choice(source="skip", matched=False)
            if choice in ("e", "edit"):
                custom = input("Enter choice letters (e.g. A or A,B) or text: ").strip()
                if q.kind in ("text", "textarea", "number"):
                    return Choice(text=custom, source="user:review", matched=True)
                picks = [ord(c.upper()) - ord("A") for c in re.findall(r"[a-zA-Z]", custom)]
                valid = [i for i in picks if 0 <= i < len(q.options)]
                if valid:
                    return Choice(indices=sorted(set(valid)), source="user:review", matched=True)
                return Choice(source="skip", matched=False)
            # fallback
            return None
        except (EOFError, KeyboardInterrupt):
            print("\nReview cancelled by user.")
            return Choice(source="skip", matched=False)
