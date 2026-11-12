"""Persistent facts for the controlled session: attempts, per-question answer lifecycle
(proposed -> applied -> saved -> verified), provider usage and metrics events.

Separate SQLite file from cache.py so the cache can be cleared without losing history.
Distinct from the cache, nothing here is an estimate: a row is written only for an
observable event."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

_SCHEMA = """
create table if not exists attempts(
  attempt_id text primary key, session_id text, url text, title text, started_at real,
  ended_at real, status text, submitted_at real, site_attempt_id text,
  score_earned real, score_total real, result_source text);
create table if not exists questions(
  attempt_id text, question_id text, question_index int, question_text text, question_type text,
  proposed text, applied text, applied_at real, saved text, saved_state text, verified text, verified_source text,
  flagged int default 0, model_used text, provider_used text, fallback_used int default 0,
  latency_ms int, confidence real, updated_at real,
  primary key(attempt_id, question_id));
create table if not exists metrics_events(
  id integer primary key autoincrement, ts real, context text, attempt_id text, question_id text,
  model text, provider text, task text, latency_ms int, fallback int default 0, ok int default 1,
  error text, tokens_prompt int, tokens_completion int);
"""


def _jd(v) -> str | None:
    return None if v is None else json.dumps(v)


def _jl(v):
    return None if v is None else json.loads(v)


class Store:
    def __init__(self, root: str | None = ".quizagent_cache"):
        self.enabled = root is not None
        if not self.enabled:
            return
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "facts.db", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self.db.commit()

    # ---------------------------------------------------------------- attempts
    def open_attempt(self, attempt_id: str, session_id: str, url: str, title: str) -> dict:
        if self.enabled:
            self.db.execute("insert or replace into attempts(attempt_id,session_id,url,title,started_at,status) "
                            "values(?,?,?,?,?,?)", (attempt_id, session_id, url, title, time.time(), "active"))
            self.db.commit()
        return {"attempt_id": attempt_id, "status": "active", "url": url, "title": title}

    def set_attempt(self, attempt_id: str, **fields) -> None:
        if not self.enabled or not fields or not self.row("attempts", attempt_id):
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"update attempts set {cols} where attempt_id=?", (*fields.values(), attempt_id))
        self.db.commit()

    def get_attempt(self, attempt_id: str) -> dict | None:
        if not self.enabled:
            return None
        r = self.db.execute("select * from attempts where attempt_id=?", (attempt_id,)).fetchone()
        return dict(r) if r else None

    def row(self, table: str, key: str) -> dict | None:
        r = self.db.execute(f"select * from {table} where attempt_id=?", (key,)).fetchone()
        return dict(r) if r else None

    # ---------------------------------------------------------------- questions
    def upsert_question(self, attempt_id: str, q: dict, **fields) -> dict:
        if not self.enabled:
            return {"attempt_id": attempt_id, **q, **fields}
        cur = self.db.execute("select * from questions where attempt_id=? and question_id=?",
                              (attempt_id, q["question_id"])).fetchone()
        base = dict(cur) if cur else {"attempt_id": attempt_id, "question_id": q["question_id"]}
        base.update({"question_index": q.get("question_index"), "question_text": q.get("question_text"),
                     "question_type": q.get("question_type")})
        for k, v in fields.items():
            base[k] = _jd(v) if k in {"proposed", "applied", "saved"} else v
        base["updated_at"] = time.time()
        cols = [c for c in base if c not in ("attempt_id", "question_id")]
        self.db.execute(
            "insert or replace into questions(attempt_id,question_id," + ",".join(cols) + ") values(?,?," +
            ",".join("?" * len(cols)) + ")", (attempt_id, q["question_id"], *[base[c] for c in cols]))
        self.db.commit()
        return self.get_question(attempt_id, q["question_id"]) or base

    def get_question(self, attempt_id: str, question_id: str) -> dict | None:
        if not self.enabled:
            return None
        r = self.db.execute("select * from questions where attempt_id=? and question_id=?",
                            (attempt_id, question_id)).fetchone()
        if not r:
            return None
        d = dict(r)
        for k in ("proposed", "applied", "saved"):
            d[k] = _jl(d.get(k))
        return d

    def questions(self, attempt_id: str) -> list[dict]:
        if not self.enabled:
            return []
        out = []
        for r in self.db.execute("select * from questions where attempt_id=? order by question_index", (attempt_id,)):
            d = dict(r)
            for k in ("proposed", "applied", "saved"):
                d[k] = _jl(d.get(k))
            out.append(d)
        return out

    # ---------------------------------------------------------------- usage / metrics
    def log_usage(self, *, context: str, model: str | None, provider: str | None, task: str | None,
                  latency_ms: int | None, fallback: bool = False, ok: bool = True, error: str | None = None,
                  attempt_id: str | None = None, question_id: str | None = None, usage: dict | None = None) -> None:
        if not self.enabled:
            return
        u = usage or {}
        self.db.execute("insert into metrics_events(ts,context,attempt_id,question_id,model,provider,task,latency_ms,"
                        "fallback,ok,error,tokens_prompt,tokens_completion) values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (time.time(), context, attempt_id, question_id, model, provider, task, latency_ms,
                         int(fallback), int(ok), error, u.get("prompt_tokens"), u.get("completion_tokens")))
        self.db.commit()

    def verified_records(self, attempt_id: str | None = None) -> list[dict]:
        if not self.enabled:
            return []
        sql, args = "select attempt_id, question_id, verified as verified_status from questions where verified is not null", ()
        if attempt_id:
            sql, args = sql + " and attempt_id=?", (attempt_id,)
        return [dict(r) for r in self.db.execute(sql, args)]

    def model_stats(self) -> list[dict]:
        if not self.enabled:
            return []
        rows = self.db.execute(
            "select model, provider, task, count(*) n, sum(fallback) fallbacks, sum(ok) ok, "
            "avg(latency_ms) avg_ms from metrics_events group by model, provider, task order by n desc").fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        if self.enabled:
            self.db.close()
