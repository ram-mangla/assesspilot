"""Answer strategies. The agent never invents answers: they come from a key file you
supply, or from a deterministic fallback (first/last/random) for flow/load testing."""
import json
import random
import re

from .model import Choice, Q
from .normalize import norm, norm_opt, norm_prompt


class NoAnswer(Exception):
    pass


class KeyStrategy:
    """key.json: {"answers":[{"match": "<substr>|re:<regex>|exact:<text>", "answer": "X" | ["X","Y"]}]}
    Answer items: option text, "#2" (1-based index), or "re:<regex>"."""

    def __init__(self, path_or_obj):
        obj = json.load(open(path_or_obj)) if isinstance(path_or_obj, str) else path_or_obj
        self.entries = obj["answers"] if isinstance(obj, dict) else obj

    def _score(self, entry, p: str) -> int:
        m = entry["match"]
        if m.startswith("re:"):
            return len(m) if re.search(m[3:], p, re.I) else 0
        if m.startswith("exact:"):
            want = norm_prompt(m[6:])
            return 10_000 if want in (p, p.rsplit(" :: ", 1)[-1]) else 0   # also matches a matching-row label
        n = norm_prompt(m)
        return len(n) if n and n in p else 0

    def choose(self, q: Q) -> Choice:
        p = norm_prompt(q.prompt)
        best = max(self.entries, key=lambda e: self._score(e, p), default=None)
        if not best or self._score(best, p) == 0:
            return Choice(matched=False)
        ans = best["answer"]
        ans = ans if isinstance(ans, list) else [ans]
        if q.kind in ("text", "textarea", "number"):
            return Choice(text=str(ans[0]), source="key")
        idx = []
        for a in ans:
            a = str(a)
            if a.startswith("#") and a[1:].isdigit():
                i = int(a[1:]) - 1
            elif a.startswith("re:"):
                i = next((k for k, o in enumerate(q.options) if re.search(a[3:], o.text, re.I)), None)
            else:
                i = q.find_option(a)
            if i is None or not (0 <= i < len(q.options)):
                return Choice(matched=False)
            idx.append(i)
        return Choice(indices=sorted(set(idx)), source="key")


class SimpleStrategy:
    def __init__(self, mode: str, rng: random.Random, text_default: str = "test"):
        self.mode, self.rng, self.text_default = mode, rng, text_default

    def choose(self, q: Q) -> Choice:
        src = f"fallback:{self.mode}"
        if q.kind in ("text", "textarea"):
            return Choice(text=self.text_default, source=src)
        if q.kind == "number":
            return Choice(text=str(self.rng.randint(1, 100)) if self.mode == "random" else "1", source=src)
        n = len(q.options)
        if n == 0:
            return Choice(matched=False)
        if self.mode == "first":
            i = [0]
        elif self.mode == "last":
            i = [n - 1]
        else:
            if q.kind == "multi" and n > 1:
                i = sorted(self.rng.sample(range(n), self.rng.randint(1, n - 1)))
            else:
                i = [self.rng.randrange(n)]
        return Choice(indices=i, source=src)


class Chain:
    """key -> ai -> cache -> fallback. Only fallback picks are cached (key and AI are read fresh)."""

    def __init__(self, key: KeyStrategy | None, fallback: str, rng: random.Random, cache,
                 use_cache=True, text_default="test", ai_strategy=None):
        self.key, self.cache, self.use_cache = key, cache, use_cache and cache.enabled
        self.fallback_mode = fallback
        self.fallback = None if fallback in ("skip", "fail") else SimpleStrategy(fallback, rng, text_default)
        self.ai = ai_strategy

    def choose(self, q: Q) -> Choice | None:
        if self.key:
            c = self.key.choose(q)
            if c.matched:
                return c
        if self.ai:
            c = self.ai.choose(q)
            if c and c.matched:
                return c
        if self.use_cache:
            texts = self.cache.get_answer(q.fp)
            if texts is not None:
                if q.kind in ("text", "textarea", "number"):
                    return Choice(text=texts[0], source="cache")
                idx = [q.find_option(t) for t in texts]
                if all(i is not None for i in idx):
                    return Choice(indices=sorted(set(idx)), source="cache")
        if self.fallback_mode == "fail":
            raise NoAnswer(f"no key entry for: {q.prompt[:80]!r}")
        if self.fallback is None:
            return None
        c = self.fallback.choose(q)
        if c.matched and self.use_cache:
            self.cache.put_answer(q.fp, c.texts(q), c.source)
        return c if c.matched else None
