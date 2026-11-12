"""Evidence-based run summary. Nothing here is estimated: a figure is reported only if the page / the run produced it,
otherwise it is None with the reason."""
import re

_KW = r"(?:score|grade|result|marks?|points?|you (?:got|scored)|total)"
_FRAC = re.compile(_KW + r"\D{0,25}?(\d+(?:\.\d+)?)\s*(?:/|out of)\s*(\d+(?:\.\d+)?)(?:\s*\(?\s*(\d+(?:\.\d+)?)\s*%\)?)?", re.I)
_PCT = re.compile(_KW + r"\D{0,25}?(\d+(?:\.\d+)?)\s*%", re.I)


def parse_score(text: str) -> dict | None:
    """Score as displayed by the site, keyword-anchored so 'Question 3 of 7' / 'Time left 09:58' never match."""
    t = re.sub(r"\s+", " ", text or "")
    m = _FRAC.search(t)
    if m:
        e, tot = float(m.group(1)), float(m.group(2))
        if tot > 0 and e <= tot:
            return {"earned": e, "total": tot, "pct": round(100 * e / tot, 1), "raw": m.group(0).strip()}
    m = _PCT.search(t)
    if m and float(m.group(1)) <= 100:
        return {"earned": None, "total": None, "pct": float(m.group(1)), "raw": m.group(0).strip()}
    return None


def summarize(report: dict) -> dict:
    answers = report.get("answers", [])
    by_src: dict[str, int] = {}
    for a in answers:
        k = a["source"].split(":")[0]
        by_src[k] = by_src.get(k, 0) + 1
    skipped = sum(1 for s in report.get("steps", []) for a in s.get("applied", []) if a.get("skipped"))
    seen = len(answers) + skipped
    phases = [s["phase"] for s in report.get("steps", [])]
    sc = parse_score(report.get("final_text_full", "") or report.get("final_text", ""))
    submitted = report.get("status") == "completed" and any(p in phases for p in ("summary", "confirm", "questions"))
    return {
        "status": report.get("status"),
        "questions_seen": seen,
        "answered": len(answers),
        "skipped": skipped,
        "answer_sources": by_src,                    # key / cache / fallback
        "key_coverage_pct": round(100 * by_src.get("key", 0) / seen, 1) if seen else None,
        "submitted": submitted,
        "score": sc,                                 # what the SITE displayed, or None
        "score_note": None if sc else "site displayed no score on the final page (not estimated)",
        "warnings": len(report.get("warnings", [])),
        "steps": len(report.get("steps", [])),
        "elapsed_s": report.get("elapsed_s"),
    }
