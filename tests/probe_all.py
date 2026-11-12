import json, subprocess, sys
urls = sys.argv[1:]
for u in urls:
    out = subprocess.run([sys.executable, "-m", "quizagent", "probe", u, "--no-cache"], capture_output=True, text=True)
    try:
        d = json.loads(out.stdout)
    except Exception:
        print(u, "PROBE FAILED", out.stderr[-400:]); continue
    print(f"\n== {u}  adapter={d['adapter']} login={d['login']}")
    for q in d["questions"]:
        print(f"  [{q['kind']:8}/{q['mode']:6}] {q['prompt'][:60]!r} opts={q['options']}")
    print("  navs:", [(n['text'], n['action'], 'modal' if n['modal'] else '') for n in d["navs"]])
