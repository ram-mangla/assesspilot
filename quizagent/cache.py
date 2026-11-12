"""SQLite cache: learned site profiles, memoized fallback answers, run log.
Login sessions (Playwright storage_state) live next to it as JSON files."""
import json
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit


class Cache:
    def __init__(self, root: str | None):
        self.enabled = root is not None
        if not self.enabled:
            return
        self.root = Path(root)
        (self.root / "state").mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "cache.db", check_same_thread=False)
        self.db.executescript("""
        create table if not exists profiles(key text primary key, adapter text, hits int default 0, last_ok real);
        create table if not exists answers(fp text primary key, texts text, source text, ts real);
        create table if not exists runs(id integer primary key, url text, adapter text, behavior text,
                                        status text, steps int, ts real, report text);
        """)

    # ---- site profiles (which adapter worked for origin+first path segment)
    @staticmethod
    def site_key(url: str) -> str:
        u = urlsplit(url)
        seg = u.path.strip("/").split("/")[0]
        return f"{u.scheme}://{u.netloc}/{seg}"

    def get_adapter(self, url: str):
        if not self.enabled:
            return None
        r = self.db.execute("select adapter from profiles where key=?", (self.site_key(url),)).fetchone()
        return r[0] if r else None

    def put_adapter(self, url: str, adapter: str):
        if not self.enabled:
            return
        self.db.execute("""insert into profiles(key,adapter,hits,last_ok) values(?,?,1,?)
                           on conflict(key) do update set adapter=excluded.adapter, hits=hits+1, last_ok=excluded.last_ok""",
                        (self.site_key(url), adapter, time.time()))
        self.db.commit()

    def drop_adapter(self, url: str):
        if self.enabled:
            self.db.execute("delete from profiles where key=?", (self.site_key(url),))
            self.db.commit()

    # ---- memoized fallback answers (texts, not indices: option order may be shuffled)
    def get_answer(self, fp: str):
        if not self.enabled:
            return None
        r = self.db.execute("select texts from answers where fp=?", (fp,)).fetchone()
        return json.loads(r[0]) if r else None

    def put_answer(self, fp: str, texts: list[str], source: str):
        if not self.enabled:
            return
        self.db.execute("insert or replace into answers values(?,?,?,?)", (fp, json.dumps(texts), source, time.time()))
        self.db.commit()

    # ---- run log
    def log_run(self, url, adapter, behavior, status, steps, report):
        if not self.enabled:
            return
        self.db.execute("insert into runs(url,adapter,behavior,status,steps,ts,report) values(?,?,?,?,?,?,?)",
                        (url, adapter, behavior, status, steps, time.time(), report))
        self.db.commit()

    def completed_urls(self) -> set:
        if not self.enabled:
            return set()
        return {r[0] for r in self.db.execute("select url from runs where status='completed'")}

    # ---- login session state
    def state_path(self, url: str) -> Path | None:
        if not self.enabled:
            return None
        u = urlsplit(url)
        return self.root / "state" / (u.netloc.replace(":", "_") + ".json")

    def stats(self) -> dict:
        if not self.enabled:
            return {}
        q = lambda t: self.db.execute(f"select count(*) from {t}").fetchone()[0]
        return {"profiles": q("profiles"), "answers": q("answers"), "runs": q("runs"),
                "states": len(list((self.root / "state").glob("*.json")))}

    def clear(self):
        if not self.enabled:
            return
        for t in ("profiles", "answers", "runs"):
            self.db.execute(f"delete from {t}")
        self.db.commit()
        for f in (self.root / "state").glob("*.json"):
            f.unlink()

    def close(self):
        if getattr(self, "db", None):
            try:
                self.db.close()
            except Exception:
                pass
            self.db = None

    def __del__(self):
        self.close()
