"""Provider gateway: route a question to a model, call NVIDIA/OpenRouter over the
OpenAI-compatible chat-completions API, normalise everything.

Failures are normalised into a value (never raised to the caller). The transport is
injectable so tests never touch a live provider."""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request

from . import MODELS, candidates_for, provider_chain
from .suggest import _coerce, _parse_json, _question_payload, _SYS
from .task_classifier import classify_task

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class ProviderError(Exception):
    def __init__(self, kind: str, message: str, status: int | None = None):
        super().__init__(message)
        self.kind = kind          # auth | rate_limit | invalid_model | unsupported_input | timeout | malformed_json | provider
        self.status = status


def _classify_error(e: Exception) -> ProviderError:
    if isinstance(e, ProviderError):
        return e
    if isinstance(e, (TimeoutError, urllib.error.URLError)) and "timed out" in str(e).lower():
        return ProviderError("timeout", str(e))
    if isinstance(e, urllib.error.HTTPError):
        status = e.code
        try:
            body = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            body = ""
        if status in (401, 403):
            kind = "auth"
        elif status == 429:
            kind = "rate_limit"
        elif status in (400, 404, 422):
            kind = "invalid_model" if "model" in body.lower() else "unsupported_input"
        else:
            kind = "provider"
        return ProviderError(kind, f"HTTP {status}: {body}", status)
    if isinstance(e, json.JSONDecodeError):
        return ProviderError("malformed_json", f"malformed provider JSON: {e}")
    return ProviderError("provider", f"{type(e).__name__}: {e}")


def http_transport(spec, payload: dict, key: str, timeout: float) -> dict:
    req = urllib.request.Request(
        spec.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "HTTP-Referer": "http://localhost/quizagent", "X-Title": "quizagent"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class Gateway:
    def __init__(self, transport=None, key_lookup=None, max_retries: int = 1, timeout: float = 45.0,
                 sleep=time.sleep, store=None, max_tokens: int = 1200):
        self.transport = transport or http_transport
        self.key_lookup = key_lookup or (lambda env: __import__("os").environ.get(env))
        self.max_retries = max_retries
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.sleep = sleep
        self.store = store
        self.rng = random.Random()

    def answer(self, question: dict, *, task: str | None = None, primary: str | None = None,
               attempt_id: str | None = None, retry_in_seconds: float = 0.8) -> dict:
        task = task or classify_task(question)
        needs_image = bool(question.get("images")) or question.get("question_type") in ("image", "diagram", "multimodal")
        try:
            chain = provider_chain(primary, task, needs_image) if primary else candidates_for(task, needs_image)
        except (RuntimeError, ValueError) as e:
            return self._fail(question, str(e), {}, [])
        errors: list[str] = []
        for n, spec in enumerate(chain):
            key = self.key_lookup(spec.key_env)
            if not key:
                errors.append(f"{spec.logical_name}: missing {spec.key_env}")
                continue
            messages = [{"role": "system", "content": _SYS}, *_question_payload(question, needs_image)]
            payload = {"model": spec.model_id, "messages": messages, "temperature": 0.2,
                       "max_tokens": self.max_tokens,
                       "response_format": {"type": "json_object"}}
            for attempt in range(self.max_retries + 1):
                t0 = time.time()
                try:
                    raw = self.transport(spec, payload, key, self.timeout)
                    content = raw["choices"][0]["message"]["content"]
                    parsed = _parse_json(content)
                    out = _coerce(parsed, question, spec.logical_name, spec.provider)
                    out.update({"fallback_used": n > 0, "latency_ms": int((time.time() - t0) * 1000),
                                "task": task, "error": None})
                    self._log(attempt_id, question, spec, task, out, raw, ok=True, fallback=n > 0)
                    return out
                except Exception as e:
                    err = _classify_error(e)
                    errors.append(f"{spec.logical_name} attempt {attempt + 1}: {err.kind}: {err}")
                    self._log(attempt_id, question, spec, task, None, None, ok=False, fallback=n > 0, error=str(err))
                    if err.kind in {"auth", "invalid_model", "unsupported_input"}:
                        break
                    if attempt < self.max_retries:
                        backoff = retry_in_seconds * (2 ** attempt) * self.rng.uniform(0.7, 1.3)
                        if err.kind == "rate_limit":
                            backoff = max(backoff, 2.0)
                        self.sleep(backoff)
        return self._fail(question, "; ".join(errors)[-1500:], {}, chain)

    def _fail(self, question, error, extra, chain) -> dict:
        return {"question_id": question.get("question_id"), "question_type": question.get("question_type"),
                "selected_options": [], "answer_text": "", "explanation": "", "confidence": 0.0,
                "status": "needs_review", "needs_review": True, "model_used": None, "provider_used": None,
                "fallback_used": False, "latency_ms": None, "error": error,
                "chain": [c.logical_name for c in chain]}

    def _log(self, attempt_id, question, spec, task, out, raw, *, ok, fallback, error=None) -> None:
        if not self.store:
            return
        usage = (raw or {}).get("usage") if isinstance(raw, dict) else None
        try:
            self.store.log_usage(context="answer", model=spec.logical_name, provider=spec.provider, task=task,
                                 latency_ms=(out or {}).get("latency_ms") if ok else None, fallback=fallback, ok=ok,
                                 error=error, attempt_id=attempt_id, question_id=question.get("question_id"),
                                 usage=usage)
        except Exception:
            pass

    @staticmethod
    def registry() -> dict:
        return {name: {"provider": s.provider, "model_id": s.model_id, "capabilities": sorted(s.capabilities)}
                for name, s in MODELS.items()}
