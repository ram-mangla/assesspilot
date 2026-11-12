"""Verified-only metrics. A result counts as correct/incorrect only when an authorized
answer key, explicit user feedback, or the quiz site's own confirmed result says so.
Confidence is never treated as correctness."""
from __future__ import annotations


def success_rate(verified_correct: int, verified_incorrect: int) -> float | None:
    total = verified_correct + verified_incorrect
    if total <= 0:
        return None
    return round(100 * verified_correct / total, 1)


def compute_verified_metrics(records: list[dict]) -> dict:
    """records: dicts with any of:
      attempt_id, question_id, verified_status: 'correct'|'incorrect'
    Unverified/skipped/failed/unanswered records are ignored.
    Regraded duplicates (same attempt_id+question_id) are not double-counted; last record wins.
    """
    latest = {}
    for r in records or []:
        status = str(r.get("verified_status", r.get("status", ""))).lower()
        if status not in {"correct", "incorrect"}:
            continue
        key = (r.get("attempt_id"), r.get("question_id"))
        if key == (None, None):
            key = (len(latest), r.get("question_id") or r.get("id") or "anonymous")
        latest[key] = status
    correct = sum(1 for s in latest.values() if s == "correct")
    incorrect = sum(1 for s in latest.values() if s == "incorrect")
    return {
        "success_rate": success_rate(correct, incorrect),
        "verified_correct": correct,
        "verified_incorrect": incorrect,
        "verified_total": correct + incorrect,
        "display": "No verified results yet" if correct + incorrect == 0 else f"{success_rate(correct, incorrect)}%",
        "note": None if correct + incorrect else "No verified results yet",
    }


def by_model(records: list[dict]) -> dict:
    """Verified tallies per model/provider. Confidence is never included: it is not accuracy."""
    buckets: dict[tuple, list[int]] = {}
    for r in records:
        status = str(r.get("verified_status", r.get("verified", ""))).lower()
        if status not in {"correct", "incorrect"}:
            continue
        key = (r.get("model_used"), r.get("provider_used"), r.get("task"))
        b = buckets.setdefault(key, [0, 0])
        b[0 if status == "correct" else 1] += 1
    return {f"{m or 'unknown'}|{p or 'unknown'}|{t or 'unknown'}":
            {"model": m, "provider": p, "task": t, "correct": c, "incorrect": i, "success_rate": success_rate(c, i)}
            for (m, p, t), (c, i) in buckets.items()}