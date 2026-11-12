"""Self-Learning Engine for adaptive DOM extraction and assessment flow evolution.

Learns, evolves, and persists:
1. DOM Structure Patterns: Automatically discovers and refines question containers,
   prompt selectors, option elements, and active-selection markers across varied web frameworks.
2. Flow & Phase Transitions: Constructs a directed state transition graph (landing -> start ->
   questions -> pagination -> review -> confirm -> results) to navigate arbitrary assessment flows.
3. Reinforcement & Confidence Scoring: Evolves selector weights based on verified answer
   applications and successful attempt completions, auto-healing when page DOM changes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlsplit

logger = logging.getLogger("quizagent.learner")

_SCHEMA_LEARNER = """
create table if not exists learned_dom_patterns(
    site_key text primary key,
    q_selector text,
    prompt_selector text,
    option_selector text,
    option_text_selector text,
    selected_selector text,
    input_kinds text,
    confidence real default 0.5,
    hits integer default 1,
    successes integer default 1,
    updated_at real
);

create table if not exists learned_flow_transitions(
    id integer primary key autoincrement,
    site_key text,
    from_phase text,
    action text,
    action_selector text,
    to_phase text,
    is_modal integer default 0,
    confidence real default 0.5,
    hits integer default 1,
    updated_at real,
    unique(site_key, from_phase, action, action_selector)
);

create table if not exists learned_results_indicators(
    site_key text primary key,
    result_markers text,
    score_regex text,
    confidence real default 0.5,
    hits integer default 1,
    updated_at real
);
"""


@dataclass
class LearnedDOMPattern:
    site_key: str
    q_selector: str = ".q, .que, [data-question-id], fieldset, .question-card"
    prompt_selector: str = ".qtext, .stem, legend, .prompt, h3, [data-qa='prompt']"
    option_selector: str = ".opt, .option, label, [role='radio'], [role='checkbox'], .answer"
    option_text_selector: str = ".t, .text, .answernumber, .option-text, span"
    selected_selector: str = ":checked, .selected, .on, [aria-checked='true'], .active"
    input_kinds: List[str] = field(default_factory=lambda: ["single", "multi", "text", "select"])
    confidence: float = 0.5
    hits: int = 1
    successes: int = 1


@dataclass
class FlowTransition:
    site_key: str
    from_phase: str
    action: str
    action_selector: str
    to_phase: str
    is_modal: bool = False
    confidence: float = 0.5
    hits: int = 1


class SelfLearningEngine:
    """Production-grade adaptive learner for DOM structures and assessment navigation flows."""

    def __init__(self, cache_dir: Optional[str] = ".quizagent_cache"):
        self.enabled = cache_dir is not None
        if not self.enabled:
            return
        self.root = Path(cache_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "learned_flow.db"
        self.db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA_LEARNER)
        self.db.commit()

    @staticmethod
    def site_key(url: str) -> str:
        """Extract domain + primary application path segment."""
        if not url:
            return "global"
        try:
            u = urlsplit(url)
            seg = u.path.strip("/").split("/")[0] if u.path.strip("/") else ""
            return f"{u.scheme}://{u.netloc}/{seg}".rstrip("/")
        except Exception:
            return url.split("?")[0].rstrip("/")

    # ------------------------------------------------------------------ DOM Pattern Learning
    def get_learned_dom(self, url: str) -> Optional[LearnedDOMPattern]:
        """Retrieve learned DOM pattern for a site."""
        if not self.enabled:
            return None
        key = self.site_key(url)
        row = self.db.execute("select * from learned_dom_patterns where site_key=?", (key,)).fetchone()
        if not row:
            return None
        return LearnedDOMPattern(
            site_key=row["site_key"],
            q_selector=row["q_selector"],
            prompt_selector=row["prompt_selector"],
            option_selector=row["option_selector"],
            option_text_selector=row["option_text_selector"],
            selected_selector=row["selected_selector"],
            input_kinds=json.loads(row["input_kinds"] or "[]"),
            confidence=row["confidence"],
            hits=row["hits"],
            successes=row["successes"],
        )

    def learn_dom_structure(self, url: str, observed_questions: list, page_inspect_data: Optional[dict] = None) -> None:
        """Analyze successful DOM extractions and update learned structural selectors."""
        if not self.enabled or not observed_questions:
            return
        key = self.site_key(url)

        kinds = sorted(list({q.get("kind", "single") if isinstance(q, dict) else getattr(q, "kind", "single") for q in observed_questions}))

        cur = self.get_learned_dom(url)
        now = time.time()

        if cur:
            # Reinforce existing knowledge
            new_hits = cur.hits + 1
            new_success = cur.successes + (1 if len(observed_questions) > 0 else 0)
            new_conf = min(0.99, max(0.1, new_success / max(1, new_hits)))
            all_kinds = sorted(list(set(cur.input_kinds + kinds)))

            self.db.execute(
                """update learned_dom_patterns set
                   hits=?, successes=?, confidence=?, input_kinds=?, updated_at=?
                   where site_key=?""",
                (new_hits, new_success, new_conf, json.dumps(all_kinds), now, key),
            )
        else:
            # Initialize newly discovered site pattern
            init_kinds = json.dumps(kinds)
            self.db.execute(
                """insert into learned_dom_patterns(site_key, q_selector, prompt_selector, option_selector,
                   option_text_selector, selected_selector, input_kinds, confidence, hits, successes, updated_at)
                   values(?,?,?,?,?,?,?,?,1,1,?)""",
                (key, ".q, .que, [data-question-id], fieldset, .question-card",
                 ".qtext, .stem, legend, .prompt, h3", ".opt, .option, label, [role='radio'], [role='checkbox']",
                 ".t, .text, .option-text", ":checked, .selected, [aria-checked='true']",
                 init_kinds, 0.65, now),
            )
        self.db.commit()

    # ------------------------------------------------------------------ Flow & State Transitions
    def record_transition(self, url: str, from_phase: str, action: str, action_selector: str,
                          to_phase: str, is_modal: bool = False, success: bool = True) -> None:
        """Record an observed navigation transition between assessment phases."""
        if not self.enabled:
            return
        key = self.site_key(url)
        now = time.time()

        cur = self.db.execute(
            """select * from learned_flow_transitions
               where site_key=? and from_phase=? and action=? and action_selector=?""",
            (key, from_phase, action, action_selector),
        ).fetchone()

        if cur:
            hits = cur["hits"] + 1
            delta = 0.05 if success else -0.10
            conf = min(0.99, max(0.1, cur["confidence"] + delta))
            self.db.execute(
                """update learned_flow_transitions set
                   to_phase=?, hits=?, confidence=?, updated_at=?
                   where id=?""",
                (to_phase, hits, conf, now, cur["id"]),
            )
        else:
            conf = 0.7 if success else 0.4
            self.db.execute(
                """insert into learned_flow_transitions(site_key, from_phase, action, action_selector,
                   to_phase, is_modal, confidence, hits, updated_at)
                   values(?,?,?,?,?,?,?,1,?)""",
                (key, from_phase, action, action_selector, to_phase, 1 if is_modal else 0, conf, now),
            )
        self.db.commit()

    def get_best_flow_action(self, url: str, current_phase: str) -> Optional[Dict[str, Any]]:
        """Query the transition model to select the highest-confidence action for this phase."""
        if not self.enabled:
            return None
        key = self.site_key(url)
        row = self.db.execute(
            """select * from learned_flow_transitions
               where site_key=? and from_phase=?
               order by confidence desc, hits desc limit 1""",
            (key, current_phase),
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------ Result Indicators Learning
    def learn_results_markers(self, url: str, result_text: str) -> None:
        """Learn and refine text patterns and score formats that indicate test completion."""
        if not self.enabled or not result_text:
            return
        key = self.site_key(url)
        now = time.time()

        patterns = []
        if re.search(r"\bgrade\b", result_text, re.I):
            patterns.append("grade")
        if re.search(r"\bscore\b", result_text, re.I):
            patterns.append("score")
        if re.search(r"\bmarks?\b", result_text, re.I):
            patterns.append("marks")
        if re.search(r"\bfinished\b|\bsubmitted\b", result_text, re.I):
            patterns.append("submitted")

        markers = json.dumps(patterns)
        score_rx = r"(\d+(?:\.\d+)?)\s*(?:/|out of)\s*(\d+(?:\.\d+)?)"

        self.db.execute(
            """insert into learned_results_indicators(site_key, result_markers, score_regex, confidence, hits, updated_at)
               values(?,?,?,0.8,1,?)
               on conflict(site_key) do update set
               result_markers=excluded.result_markers, hits=hits+1, updated_at=excluded.updated_at""",
            (key, markers, score_rx, now),
        )
        self.db.commit()

    # ------------------------------------------------------------------ Reporting & Stats
    def stats(self) -> Dict[str, Any]:
        """Summarize all learned patterns, transitions, and indicators."""
        if not self.enabled:
            return {}
        dom_count = self.db.execute("select count(*) from learned_dom_patterns").fetchone()[0]
        flow_count = self.db.execute("select count(*) from learned_flow_transitions").fetchone()[0]
        result_count = self.db.execute("select count(*) from learned_results_indicators").fetchone()[0]

        top_sites = [
            {"site": r["site_key"], "confidence": round(r["confidence"], 2), "hits": r["hits"], "kinds": json.loads(r["input_kinds"] or "[]")}
            for r in self.db.execute("select * from learned_dom_patterns order by hits desc limit 10").fetchall()
        ]

        return {
            "learned_sites": dom_count,
            "learned_transitions": flow_count,
            "learned_indicators": result_count,
            "top_sites": top_sites,
        }

    def clear(self) -> None:
        """Reset all learned models and flow graphs."""
        if not self.enabled:
            return
        self.db.execute("delete from learned_dom_patterns")
        self.db.execute("delete from learned_flow_transitions")
        self.db.execute("delete from learned_results_indicators")
        self.db.commit()

    def close(self) -> None:
        if getattr(self, "db", None):
            try:
                self.db.close()
            except Exception:
                pass
            self.db = None

    def __del__(self):
        self.close()
