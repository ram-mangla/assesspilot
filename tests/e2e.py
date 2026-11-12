"""End-to-end matrix against testsite/app.py. Verifies the SERVER-side recorded submission,
not just the agent's own report. Usage: python tests/e2e.py [filter-substring]"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

BASE = "http://127.0.0.1:5055"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "testsite"))
import app as site  # noqa: E402  (bank only, server runs separately)

from quizagent import cli  # noqa: E402

TMP = os.path.join(tempfile.gettempdir(), "qa_e2e").replace("\\", "/")
KEY = f"{TMP}/key.json"


def get(path):
    return json.load(urllib.request.urlopen(BASE + path))


def reset():
    urllib.request.urlopen(BASE + "/_reset").read()


def run(url, *args, cache=None):
    argv = ["run", url, "--out", f"{TMP}/runs", "--seed", "3"]
    argv += ["--cache-dir", cache] if cache else ["--no-cache"]
    argv += list(args)
    rc = cli.main(argv)
    runs = sorted(os.listdir(f"{TMP}/runs"))
    runs = [r for r in runs if r.startswith("run-")]
    rep = json.load(open(f"{TMP}/runs/{runs[-1]}"))
    return rc, rep


def qid_of(prompt):
    if " :: " in prompt:
        prompt = prompt.rsplit(" :: ", 1)[-1]
    for q in site.FORM_BANK:
        if q["text"] in prompt:
            return str(q["id"])
    m = {c: f"8_{i}" for i, (c, _) in enumerate(site.MATCH[0]["rows"])}
    return m.get(prompt.strip())


def consistent(rep, srv):
    """agent-claimed choices == server-recorded answers"""
    bad = []
    for a in rep["answers"]:
        qid = qid_of(a["prompt"])
        got = sorted(site.n(x) for x in srv["answers"].get(qid, []))
        want = sorted(site.n(x) for x in a["chosen"] if x != "")
        if got != want:
            bad.append((a["prompt"][:30], want, got))
    return bad


CASES = []


def case(name):
    def deco(f):
        CASES.append((name, f))
        return f
    return deco


def full_score(rep, srv, total):
    return srv.get("score") == total and srv.get("total") == total and rep["status"] == "completed"


KEYARG = ["--key", KEY]


@case("single/key")
def _():
    rc, rep = run(f"{BASE}/single", *KEYARG); s = get("/_results/single")
    return full_score(rep, s, 8) and not consistent(rep, s), rep, s


@case("single-alt-layout/key")
def _():
    rc, rep = run(f"{BASE}/single?layout=alt", *KEYARG); s = get("/_results/single")
    return full_score(rep, s, 8) and not consistent(rep, s), rep, s


@case("iframe/key")
def _():
    rc, rep = run(f"{BASE}/iframe", *KEYARG); s = get("/_results/single")
    return full_score(rep, s, 8) and not consistent(rep, s), rep, s


@case("shadow-dom/key")
def _():
    rc, rep = run(f"{BASE}/shadow", *KEYARG); s = get("/_results/shadow")
    return full_score(rep, s, 8) and not consistent(rep, s), rep, s


@case("paged+summary+modal/key")
def _():
    rc, rep = run(f"{BASE}/paged", *KEYARG); s = get("/_results/paged")
    phases = [x["phase"] for x in rep["steps"]]
    return full_score(rep, s, 7) and not consistent(rep, s) and "summary" in phases and "confirm" in phases, rep, s


@case("paged/erratic-behavior(revisit,changes)")
def _():
    rc, rep = run(f"{BASE}/paged", *KEYARG, "--behavior", "erratic", "--speed", "40"); s = get("/_results/paged")
    return full_score(rep, s, 7) and not consistent(rep, s), rep, s


@case("paged/student-behavior")
def _():
    rc, rep = run(f"{BASE}/paged", *KEYARG, "--behavior", "student", "--speed", "40"); s = get("/_results/paged")
    return full_score(rep, s, 7) and not consistent(rep, s), rep, s


@case("timed(native confirm())/key")
def _():
    rc, rep = run(f"{BASE}/timed", *KEYARG); s = get("/_results/timed")
    return full_score(rep, s, 8) and not consistent(rep, s) and any("confirm" in d for d in rep["dialogs"]), rep, s


@case("spa-aria/key")
def _():
    rc, rep = run(f"{BASE}/spa?mode=aria&site=spa_aria", *KEYARG); s = get("/_results/spa_aria")
    return full_score(rep, s, 7) and not consistent(rep, s), rep, s


@case("spa-div(no roles)/generic-heuristic/key")
def _():
    rc, rep = run(f"{BASE}/spa?mode=div&site=spa_div", *KEYARG); s = get("/_results/spa_div")
    return full_score(rep, s, 7) and not consistent(rep, s), rep, s


@case("spa-div+async(1.5s)/config-profile/key")
def _():
    rc, rep = run(f"{BASE}/spa?mode=div&delay=1500&site=spa_cfg", *KEYARG, "--config", f"{ROOT}/examples/spa_div.json"); s = get("/_results/spa_cfg")
    return full_score(rep, s, 7) and not consistent(rep, s) and rep["adapter"].startswith("config"), rep, s


@case("spa-div+async(1.5s)/heuristic/behavior=student")
def _():
    rc, rep = run(f"{BASE}/spa?mode=div&delay=1500&site=spa_st", *KEYARG, "--behavior", "student", "--speed", "40"); s = get("/_results/spa_st")
    return full_score(rep, s, 7) and not consistent(rep, s), rep, s


@case("report honesty: reported score == server score with deliberately wrong answers")
def _():
    rc, rep = run(f"{BASE}/single", "--fallback", "first"); s = get("/_results/single")
    sc = rep["summary"]["score"]
    ok = sc is not None and sc["earned"] == s["score"] and sc["total"] == s["total"] and s["score"] < s["total"] \
        and rep["summary"]["answer_sources"] == {"fallback": 9} and rep["summary"]["key_coverage_pct"] == 0.0
    return ok, rep, {"summary_score": sc, "server": [s["score"], s["total"]]}


@case("report honesty: site shows no score -> score None, nothing invented")
def _():
    rc, rep = run(f"{BASE}/single?noscore=1", *KEYARG); s = get("/_results/single")
    sm = rep["summary"]
    return rep["status"] == "completed" and sm["score"] is None and sm["score_note"] and sm["submitted"] and s.get("score") == 8, rep, sm


@case("report: key coverage + score from page on full-key run")
def _():
    rc, rep = run(f"{BASE}/timed", *KEYARG); s = get("/_results/timed")
    sm = rep["summary"]
    return sm["key_coverage_pct"] == 100.0 and sm["score"]["earned"] == s["score"] == 8 and sm["skipped"] == 0, rep, sm


@case("moodle-shaped DOM fixture (moodle adapter, scoped scan)")
def _():
    rc, rep = run(f"{BASE}/moodle-like", *KEYARG); s = get("/_results/moodle_like")
    return rep["adapter"] == "moodle" and rep["status"] == "completed" and s.get("score") == 5 and not consistent(rep, s), rep, s


def auto(url, *args, cache=None):
    argv = ["auto", url, "--out", f"{TMP}/runs", "--seed", "3"] + (["--cache-dir", cache] if cache else ["--no-cache"]) + list(args)
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.main(argv)
    return json.loads(buf.getvalue())


@case("autopilot: hub site, nested nav, junk links, --pick")
def _():
    d = auto(f"{BASE}/hub", *KEYARG, "--pick", "Networking")
    s = get("/_results/single")
    ok = len(d["runs"]) == 1 and d["runs"][0]["status"] == "completed" and s.get("score") == 8
    return ok, {"status": "completed", "steps": [], "answers": [], "warnings": []}, {"found": d["found"], "log": d["log"][:6], "server": s.get("score")}


@case("autopilot: login page start + creds -> finds quiz")
def _():
    os.environ["QA_PASS"] = "demo123"
    d = auto(f"{BASE}/login", *KEYARG, "--user", "demo")
    s = get("/_results/secure")
    ok = len(d["runs"]) == 1 and d["runs"][0]["status"] == "completed" and s.get("score") == 8
    return ok, {"status": "completed", "steps": [], "answers": [], "warnings": []}, {"found": d["found"], "server": s.get("score")}


@case("autopilot: --list attempts nothing")
def _():
    d = auto(f"{BASE}/hub", "--list")
    return len(d["found"]) >= 1 and d["runs"] == [] and get("/_results/single") == {}, {"status": "completed", "steps": [], "answers": [], "warnings": []}, d["found"]


def _phases(rep):
    return [x["phase"] for x in rep["steps"]]


@case("profile mode: log in once, reuse profile with NO credentials")
def _():
    prof = f"{TMP}/prof"
    shutil.rmtree(prof, ignore_errors=True)
    os.environ["QA_PASS"] = "demo123"
    rc, r1 = run(f"{BASE}/secure", *KEYARG, "--user", "demo", "--profile", prof); s1 = get("/_results/secure")
    reset()
    os.environ.pop("QA_PASS")
    rc, r2 = run(f"{BASE}/secure", *KEYARG, "--profile", prof); s2 = get("/_results/secure")
    ok = full_score(r1, s1, 8) and full_score(r2, s2, 8) and "login" in _phases(r1) and "login" not in _phases(r2)
    return ok, r2, {"run1": _phases(r1), "run2": _phases(r2)}


@case("cdp attach: already-logged-in Chrome, direct URL, no creds, browser survives")
def _():
    from playwright.sync_api import sync_playwright
    port, ud = 9444, f"{TMP}/cdp_chrome"
    shutil.rmtree(ud, ignore_errors=True)
    proc = subprocess.Popen(["google-chrome", "--headless=new", "--no-sandbox", f"--remote-debugging-port={port}", f"--user-data-dir={ud}", "--no-first-run", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _i in range(40):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version"); break
            except Exception:
                time.sleep(0.25)
        with sync_playwright() as p:                       # the "human" logs in
            b = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            pg = b.contexts[0].pages[0]
            pg.goto(f"{BASE}/login"); pg.fill("[name=username]", "demo"); pg.fill("[name=password]", "demo123")
            with pg.expect_navigation():
                pg.click("button")
        os.environ.pop("QA_PASS", None)
        reset()
        rc, rep = run(f"{BASE}/secure", *KEYARG, "--cdp", f"http://127.0.0.1:{port}"); s = get("/_results/secure")
        alive = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version").status == 200
        return full_score(rep, s, 8) and "login" not in _phases(rep) and alive, rep, {"phases": _phases(rep), "alive": alive}
    finally:
        proc.terminate()


@case("login+session-cache")
def _():
    c = f"{TMP}/cache_login"
    shutil.rmtree(c, ignore_errors=True)
    os.environ["QA_PASS"] = "demo123"
    rc1, rep1 = run(f"{BASE}/secure", *KEYARG, "--user", "demo", cache=c); s1 = get("/_results/secure")
    reset()
    rc2, rep2 = run(f"{BASE}/secure", *KEYARG, "--user", "demo", cache=c); s2 = get("/_results/secure")
    p1 = [x["phase"] for x in rep1["steps"]]; p2 = [x["phase"] for x in rep2["steps"]]
    ok = full_score(rep1, s1, 8) and full_score(rep2, s2, 8) and "login" in p1 and "login" not in p2
    return ok, rep2, {"run1_phases": p1, "run2_phases": p2}


@case("fallback=random: server received exactly what agent chose")
def _():
    rc, rep = run(f"{BASE}/single", "--fallback", "random"); s = get("/_results/single")
    return rep["status"] == "completed" and not consistent(rep, s) and len(rep["answers"]) == 9, rep, s


@case("answer-cache: 2nd run reuses memoized fallback picks, --fresh ignores")
def _():
    c = f"{TMP}/cache_ans"
    shutil.rmtree(c, ignore_errors=True)
    rc, r1 = run(f"{BASE}/single", "--fallback", "random", "--seed", "11", cache=c); s1 = get("/_results/single")
    rc, r2 = run(f"{BASE}/single", "--fallback", "random", "--seed", "99", cache=c); s2 = get("/_results/single")
    rc, r3 = run(f"{BASE}/single", "--fallback", "random", "--seed", "99", "--fresh", cache=c); s3 = get("/_results/single")
    same12 = [a["chosen"] for a in r1["answers"]] == [a["chosen"] for a in r2["answers"]]
    srcs = {a["source"] for a in r2["answers"]}
    diff3 = [a["chosen"] for a in r1["answers"]] != [a["chosen"] for a in r3["answers"]]
    return same12 and srcs == {"cache"} and diff3 and not consistent(r2, s2), r2, {"same12": same12, "r2_sources": sorted(srcs), "fresh_differs": diff3}


@case("adapter-cache: site profile learned after success")
def _():
    c = f"{TMP}/cache_ans"
    out = subprocess.run([sys.executable, "-m", "quizagent", "cache", "show", "--cache-dir", c], capture_output=True, text=True, cwd=ROOT)
    st = json.loads(out.stdout)
    return st["profiles"] >= 1 and st["answers"] >= 9 and st["runs"] >= 3, {"status": "n/a", "steps": [], "answers": []}, st


@case("key missing + fallback=fail -> fails loudly, submits nothing")
def _():
    partial = f"{TMP}/partial.json"
    json.dump({"answers": [{"match": "idempotent", "answer": "PUT"}]}, open(partial, "w"))
    rc, rep = run(f"{BASE}/single", "--key", partial, "--fallback", "fail"); s = get("/_results/single")
    return rep["status"].startswith("failed: no key entry") and s == {}, rep, s


@case("key + fallback=skip leaves unknown questions blank")
def _():
    partial = f"{TMP}/partial.json"
    rc, rep = run(f"{BASE}/single", "--key", partial, "--fallback", "skip"); s = get("/_results/single")
    return rep["status"] == "completed" and [k for k, v in s["answers"].items() if v] == ["1"], rep, s


def main():
    os.makedirs(TMP, exist_ok=True)
    shutil.rmtree(f"{TMP}/runs", ignore_errors=True)
    open(KEY, "w").write(urllib.request.urlopen(BASE + "/_key.json").read().decode())
    flt = sys.argv[1] if len(sys.argv) > 1 else ""
    fails = 0
    for name, f in CASES:
        if flt not in name:
            continue
        if name != "adapter-cache: site profile learned after success" and not name.startswith("login"):
            reset()
        t = time.time()
        try:
            ok, rep, srv = f()
        except Exception as e:  # noqa
            ok, rep, srv = False, {"status": f"EXC {type(e).__name__}: {e}", "warnings": []}, {}
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name:62} {time.time() - t:5.1f}s")
        if not ok:
            print("     status:", rep.get("status"), "| server:", json.dumps(srv)[:300])
            print("     warnings:", rep.get("warnings"))
            print("     steps:", [(x['phase'], x.get('click')) for x in rep.get("steps", [])][:14])
    print(f"\n{len([c for c in CASES if flt in c[0]]) - fails} passed, {fails} failed")
    return fails


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
