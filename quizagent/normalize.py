import hashlib
import re
import unicodedata

_ENUM = re.compile(r"^\s*(?:\(?[a-zA-Z0-9]{1,2}[.)]|[•\-–])\s+")
_NOISE = [
    r"\b\d{1,2}:\d{2}(?::\d{2})?\b",           # timers
    r"\bquestion \d+( of \d+)?\b",
    r"\bmarked out of [\d.]+\b",
    r"\bnot yet answered\b",
    r"\bflag question\b",
    r"\bselect (one|all that apply)\s*:?",
    r"\bchoose (one|all)\b[^.?:]*[:.]?",
]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"\s+", " ", s).strip()


def norm_opt(s: str) -> str:
    return _ENUM.sub("", norm(s)).strip(" .:;,!?")


def norm_prompt(s: str) -> str:
    s = norm(s)
    for p in _NOISE:
        s = re.sub(p, " ", s)
    return re.sub(r"\s+", " ", s).strip(" .:;,!?")


def fingerprint(prompt: str, options: list[str]) -> str:
    raw = norm_prompt(prompt) + "|" + "|".join(sorted(norm_opt(o) for o in options))
    return hashlib.sha1(raw.encode()).hexdigest()[:12]
