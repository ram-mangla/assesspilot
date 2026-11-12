"""Task classification: decides which registry task answers a question."""
from __future__ import annotations

import re

CODE_RX = re.compile(r"(```|\bdef \w+\(|\bclass \w+|<code>|</?pre>|\bfunction \w+\(|;\s*$|\bconsole\.log\()", re.M | re.I)
IMAGE_TYPES = {"image", "diagram", "multimodal"}


def classify_task(question: dict) -> str:
    qtype = question.get("question_type") or ""
    text = question.get("question_text") or ""
    if question.get("images") or qtype in IMAGE_TYPES:
        return "multimodal" if qtype == "multimodal" else "vision"
    if question.get("code_block") or qtype == "code" or CODE_RX.search(text):
        return "code"
    opts = question.get("options") or []
    if qtype in ("single_choice", "multiple_choice", "true_false") and len(opts) >= 2:
        # a short reasoning ask over a few options: inexpensive general model is enough
        return "reasoning" if len(text) > 400 or re.search(r"\bwhy\b|\bexplain\b|\bprove\b|\bcalculate\b", text, re.I) else "general"
    if len(text) > 600:
        return "reasoning"
    return "general"
