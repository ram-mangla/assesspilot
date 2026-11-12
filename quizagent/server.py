"""Local control dashboard: real browser session, quiz controls, LLM answer pipeline.

Binds 127.0.0.1 only; every request must carry the per-run token (the dashboard drives a
real browser). Provider keys stay in this process: they are only reported as present/probably-missing."""
from __future__ import annotations

import argparse
import functools
import json
import logging
import secrets
import uuid

from flask import Flask, jsonify, request

from . import metrics, session_state as S
from .llm import capabilities_summary, missing_keys, task_map
from .quiz_session import QuizSession
from .session import ManualBrowserSession
from .store import Store

log = logging.getLogger("quizagent.server")


def create_app(store: Store | None = None, browser_factory=None, gateway=None, token: str | None = None,
               cache_dir: str = ".quizagent_cache") -> Flask:
    app = Flask(__name__)
    app.config["TOKEN"] = token or secrets.token_urlsafe(16)
    store = store or Store(cache_dir)
    browser_holder: dict = {}

    def browser() -> ManualBrowserSession:
        if "b" not in browser_holder:
            browser_holder["b"] = (browser_factory or ManualBrowserSession)()
        return browser_holder["b"]

    def quiz() -> QuizSession:
        if "q" not in browser_holder:
            browser_holder["q"] = QuizSession(browser(), store=store, gateway=gateway)
        return browser_holder["q"]

    def auth(fn):
        @functools.wraps(fn)
        def inner(*a, **kw):
            supplied = request.args.get("t") or request.headers.get("X-Quiz-Token") or (
                (request.get_json(silent=True) or {}).get("token") if request.method == "POST" else None)
            if not secrets.compare_digest(str(supplied or ""), app.config["TOKEN"]):
                return jsonify({"error": "missing or invalid token"}), 403
            return fn(*a, **kw)
        return inner

    def body() -> dict:
        return request.get_json(silent=True) or {}

    def run(fn):
        """Correlation id per request; state conflicts become 409, everything else 500 with the id."""
        @functools.wraps(fn)
        @auth
        def inner(*a, **kw):
            rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:8]
            try:
                res = fn(*a, **kw)
                if isinstance(res, tuple):
                    return res
                return jsonify({"request_id": rid, "ok": True, **res})
            except S.StateConflict as e:
                log.warning("conflict rid=%s %s %s", rid, request.path, e)
                return jsonify({"request_id": rid, "ok": False, "error": str(e), "kind": "state_conflict"}), 409
            except ValueError as e:
                return jsonify({"request_id": rid, "ok": False, "error": str(e), "kind": "invalid"}), 400
            except Exception as e:  # noqa: BLE001
                log.exception("error rid=%s %s", rid, request.path)
                return jsonify({"request_id": rid, "ok": False, "error": f"{type(e).__name__}: {e}",
                                "kind": "error"}), 500
        return inner

    # ------------------------------------------------------------------ session
    @app.post("/browser/session/start")
    @run
    def session_start():
        url = body().get("url")
        if not url:
            raise ValueError("url is required")
        res = quiz().start(url, headed=body().get("headed", True))
        return {**res, "browser": quiz().status().get("browser")}

    @app.post("/browser/session/navigate")
    @run
    def session_navigate():
        return quiz().navigate(body().get("url") or "")

    @app.post("/browser/session/refresh")
    @run
    def session_refresh():
        return quiz().reload()

    @app.post("/browser/session/back")
    @run
    def session_back():
        return quiz().history("back")

    @app.post("/browser/session/forward")
    @run
    def session_forward():
        return quiz().history("forward")

    @app.post("/browser/session/stop")
    @run
    def session_stop():
        return quiz().stop()

    @app.get("/browser/session/status")
    @run
    def session_status():
        return quiz().status()

    @app.get("/browser/session/screenshot")
    @run
    def session_shot():
        return {"screenshot": quiz().screenshot(bool(request.args.get("full")))}

    @app.get("/browser/session/tabs")
    @run
    def session_tabs():
        return {"tabs": quiz().tabs()}

    @app.post("/browser/session/tab")
    @run
    def session_tab():
        return {"browser": quiz().switch_tab(int(body().get("index", 0)))}

    @app.post("/browser/session/popup")
    @run
    def session_popup():
        return quiz().adopt_popup()

    # ------------------------------------------------------------------ quiz
    @app.post("/quiz/detect")
    @run
    def quiz_detect():
        return quiz().detect()

    @app.get("/quiz/current-question")
    @run
    def quiz_current():
        return quiz().current_question()

    @app.post("/quiz/answer")
    @run
    def quiz_answer():
        return quiz().answer(apply=bool(body().get("apply")))

    @app.post("/quiz/answer/apply")
    @run
    def quiz_apply():
        return quiz().apply()

    @app.post("/quiz/answer/save")
    @run
    def quiz_save():
        return quiz().save()

    @app.post("/quiz/question/next")
    @run
    def quiz_next():
        return quiz().move("next")

    @app.post("/quiz/question/previous")
    @run
    def quiz_previous():
        return quiz().move("previous")

    @app.post("/quiz/question/jump")
    @run
    def quiz_jump():
        return quiz().jump(int(body().get("index") or 1))

    @app.post("/quiz/question/flag")
    @run
    def quiz_flag():
        return quiz().flag(body().get("question_id"), bool(body().get("flagged", True)))

    @app.post("/quiz/question/verify")
    @run
    def quiz_verify():
        return quiz().mark_verified(body().get("question_id") or "", body().get("status") or "",
                                    body().get("source") or "user feedback")

    @app.get("/quiz/progress")
    @run
    def quiz_progress():
        return quiz().progress()

    @app.get("/quiz/review")
    @run
    def quiz_review():
        return quiz().review()

    # ------------------------------------------------------------------ attempt
    @app.post("/quiz/attempt/start")
    @run
    def attempt_start():
        return quiz().start_attempt()

    @app.post("/quiz/attempt/pause")
    @run
    def attempt_pause():
        return quiz().pause()

    @app.post("/quiz/attempt/resume")
    @run
    def attempt_resume():
        return quiz().resume()

    @app.post("/quiz/attempt/stop")
    @run
    def attempt_stop():
        return quiz().stop_run()

    @app.post("/quiz/attempt/run")
    @run
    def attempt_run():
        q = quiz()
        if "auto_submit" in body():
            q.auto_submit = bool(body()["auto_submit"])
        return q.run_mode(body().get("mode") or "assisted_attempt")

    @app.post("/quiz/attempt/submit")
    @run
    def attempt_submit():
        confirm = bool(body().get("confirm"))
        q = quiz()
        if body().get("auto_submit") is True:
            q.auto_submit = True
            return q.submit(confirm=confirm, automated=True)
        return q.submit(confirm=confirm)

    @app.get("/quiz/attempt/results")
    @run
    def attempt_results():
        return quiz().results()

    # ------------------------------------------------------------------ models / metrics
    @app.get("/ai/models")
    @run
    def ai_models():
        return {"models": capabilities_summary(), "tasks": task_map(), "missing_keys": missing_keys()}

    @app.get("/metrics/summary")
    @run
    def metrics_summary():
        attempt_id = request.args.get("attempt_id")
        records = store.verified_records(attempt_id)
        return {"verified": metrics.compute_verified_metrics(records),
                "by_model_and_task": metrics.by_model(records),
                "usage": store.model_stats()}

    @app.get("/")
    @app.post("/")
    def index():
        return _DASHBOARD.replace("__TOKEN__", app.config["TOKEN"])

    return app


def serve(port: int = 8765, cache_dir: str = ".quizagent_cache", out: str = "runs") -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = create_app(Store(cache_dir), cache_dir=cache_dir)
    print(f"quizagent dashboard: http://127.0.0.1:{port}/?t={app.config['TOKEN']}", flush=True)
    if missing_keys():
        print(f"WARNING: missing provider keys: {', '.join(missing_keys())} - read/apply work, answers will need_review",
              flush=True)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


_DASHBOARD = r"""<!doctype html><html><head><meta charset="utf-8"><title>quizagent</title>
<style>
:root{--bg:#12141a;--panel:#1b1e27;--line:#2c3040;--txt:#e6e8ee;--dim:#98a0b3;--acc:#7ab8ff;--warn:#f0b23a;--bad:#e06060;--ok:#4cc38a}
*{box-sizing:border-box}body{margin:0;font:14px/1.4 system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--txt)}
header{display:flex;gap:8px;align-items:center;padding:10px 14px;background:var(--panel);border-bottom:1px solid var(--line);flex-wrap:wrap}
input,select,button{font:inherit;background:#0f1117;color:var(--txt);border:1px solid var(--line);border-radius:6px;padding:6px 9px}
button{cursor:pointer;background:#232837}button:hover{border-color:var(--acc)}button.on{border-color:var(--ok);color:var(--ok)}
button.danger{border-color:var(--bad);color:#f7b7b7}
main{display:grid;grid-template-columns:1fr 420px;gap:12px;padding:12px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px}
.panel h2{margin:0 0 8px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--dim)}
#shot{width:100%;border-radius:6px;border:1px solid var(--line);background:#000;min-height:120px}
.row{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px}
.kv{display:grid;grid-template-columns:130px 1fr;gap:2px 8px;font-size:13px}
.kv b{color:var(--dim);font-weight:500}
.state{display:inline-block;padding:2px 8px;border-radius:10px;background:#232837;color:var(--acc);font-size:12px}
.opt{display:block;padding:4px 6px;border-radius:4px;margin:2px 0}
.opt.sel{background:#1f3a2c;color:#a9e8c4}.opt.prop{background:#22334d;color:#bfe0ff}
.err{color:#f7b7b7;font-size:12px;white-space:pre-wrap}.muted{color:var(--dim);font-size:12px}
pre{white-space:pre-wrap;font-size:12px;color:var(--dim);max-height:180px;overflow:auto;margin:0}
</style></head><body>
<header>
  <input id="url" placeholder="https://… quiz page" style="flex:1;min-width:320px">
  <button onclick="start()">Open URL</button>
  <button onclick="act('/browser/session/refresh')">Refresh</button>
  <button onclick="act('/browser/session/back')">Back</button>
  <button onclick="act('/browser/session/forward')">Forward</button>
  <button class="danger" onclick="act('/browser/session/stop')">Close browser</button>
</header>
<main>
 <section class="panel">
  <h2>Page</h2>
  <img id="shot" alt="live page screenshot">
  <div class="row" style="margin-top:8px">
   <button onclick="act('/quiz/detect')">Inspect page</button>
   <button onclick="act('/quiz/current-question')">Read current question</button>
   <button onclick="act('/quiz/attempt/start')">Start attempt</button>
   <button onclick="act('/quiz/question/previous')">Previous question</button>
   <button onclick="act('/quiz/question/next')">Next question</button>
   <button onclick="act('/quiz/question/flag',{flagged:true})">Flag for review</button>
   <button onclick="act('/quiz/attempt/pause')">Pause</button>
   <button onclick="act('/quiz/attempt/resume')">Resume</button>
   <button onclick="act('/quiz/attempt/stop')">Stop</button>
  </div>
  <div class="kv" id="dbg"></div>
 </section>
 <section class="panel">
  <h2>Question &amp; answer</h2>
  <div class="kv" id="qhead"></div>
  <div id="qtext" style="margin:6px 0;font-size:15px"></div>
  <div id="opts"></div>
  <div class="row" style="margin-top:8px">
   <button onclick="act('/quiz/answer',{apply:false})">Answer current</button>
   <button onclick="act('/quiz/answer/apply')">Apply answer</button>
   <button onclick="act('/quiz/answer/save')">Save answer</button>
   <button onclick="act('/quiz/answer',{apply:true})">Answer + apply</button>
   <button onclick="act('/quiz/review')">Review answers</button>
  </div>
  <div class="kv" id="ans"></div>
  <h2 style="margin-top:12px">Attempt</h2>
  <div class="row">
   <select id="mode"><option value="assist">AI assistance (manual)</option>
   <option value="assisted_attempt">Assisted attempt</option>
   <option value="practice_automation">Authorized practice automation</option></select>
   <button onclick="act('/quiz/attempt/run',{mode:document.getElementById('mode').value})">Run mode</button>
   <label class="muted"><input type="checkbox" id="autosub"> allow automated final submission</label>
  </div>
  <div class="row">
   <button onclick="act('/quiz/attempt/submit',{confirm:false})">Submission preview</button>
   <button class="danger" onclick="if(confirm('Submit this attempt now? This is irreversible.'))act('/quiz/attempt/submit',{confirm:true})">Submit attempt</button>
   <button onclick="act('/quiz/attempt/results')">Results</button>
   <button onclick="loadMetrics()">Verified metrics</button>
  </div>
  <div class="kv" id="res"></div>
  <h2 style="margin-top:12px">Log</h2>
  <pre id="log"></pre>
 </section>
</main>
<script>
const T = new URLSearchParams(location.search).get('t') || '__TOKEN__';
let timer=null, lastState='';
async function call(path, body){
  const r = await fetch(path + (path.includes('?')?'&':'?') + 't=' + encodeURIComponent(T), {
    method: body===undefined ? 'GET' : 'POST',
    headers: {'Content-Type':'application/json','X-Quiz-Token':T},
    body: body===undefined ? undefined : JSON.stringify(body)});
  return await r.json();
}
function logMsg(o){ const el=document.getElementById('log'); el.textContent = new Date().toLocaleTimeString()+'  '+JSON.stringify(o).slice(0,1200)+'\n'+el.textContent; }
async function act(path, body){ try{ const o = await call(path, body||{}); logMsg({path, ok:o.ok, error:o.error}); render(o); }catch(e){ logMsg({path, error:String(e)}); } }
async function start(){ await act('/browser/session/start', {url: document.getElementById('url').value, headed:true}); poll(); }
function el(id){ return document.getElementById(id); }
function render(o){
  const d = o.detection; const st = (o.state||{}).state || (d&&d.state);
  if (o.browser) Object.assign(el('dbg').dataset, {});
  if (d){
    el('dbg').innerHTML = `<b>url</b><span>${d.quiz_title||''} — ${(d.current_question&&d.current_question.page_url)||''}</span>
      <b>quiz</b><span>${d.is_quiz?'yes':'not detected'} · ${d.question_count||0} question(s) on page</span>
      <b>progress</b><span>${d.progress&&d.progress.index?d.progress.index+' / ':(d.progress&&d.progress.total?'? / '+d.progress.total:'unknown')}</span>
      <b>timer</b><span>${d.timer||'not exposed'}</span>
      <b>login</b><span>${d.login_required?'required (log in manually in the browser window)':'not required'}</span>`;
  }
  if (o.current || (o.detection&&d.current_question)){
    const q = o.current || d.current_question;
    el('qhead').innerHTML = `<b>state</b><span class="state">${st||''}</span><b>number</b><span>${q.question_index||'?'} of ${q.total_questions||'?'}</span>
      <b>type</b><span>${q.question_type}</span><b>saved</b><span>${q.saved_state_text||'unknown'}</span>`;
    el('qtext').textContent = q.question_text||'';
    const prop = (o.answer||o.last_answer||{}).selected_options||[];
    el('opts').innerHTML = (q.options||[]).map(x=>`<span class="opt ${x.selected?'sel':''} ${prop.includes(x.id)?'prop':''}">[${x.id}] ${x.text}</span>`).join('') || '<span class="muted">(no options — free text answer)</span>';
  }
  const a = o.answer || o.last_answer;
  if (a) el('ans').innerHTML = `<b>proposed</b><span>${(a.selected_options||[]).join(', ')||a.answer_text||''}</span>
    <b>status</b><span>${a.status}</span><b>confidence</b><span>${a.confidence} (not correctness)</span>
    <b>model</b><span>${a.model_used||'—'} (${a.provider_used||'—'})${a.fallback_used?' [fallback]':''}</span>
    <b>explanation</b><span>${a.explanation||''}</span><b>error</b><span class="err">${a.error||''}</span>`;
  if (o.preview || o.attempt || o.score !== undefined || o.verified_metrics)
    el('res').innerHTML = `<b>attempt</b><span>${JSON.stringify(o.attempt||o.attempt_id||'—')}</span>
      <b>preview</b><span>${o.preview?JSON.stringify(o.preview):'—'}</span>
      <b>results</b><span>${o.note||''} ${o.score?JSON.stringify(o.score):''}</span>
      <b>verified</b><span>${o.verified_metrics?o.verified_metrics.display:'—'}</span>`;
  if (o.error) logMsg({error:o.error});
}
async function poll(){
  if (timer) clearInterval(timer);
  timer = setInterval(async ()=>{
    try{
      const s = await call('/browser/session/status');
      if (!s.browser || !s.browser.connected) return;
      const shot = await call('/browser/session/screenshot');
      if (shot.screenshot) el('shot').src = shot.screenshot;
      const key = JSON.stringify(s.session);
      if (key !== lastState){ lastState = key; document.title = 'quizagent · ' + s.session.state; }
      const d = document.createElement('div');
      render({state: s.session, last_answer: s.last_answer});
      if (s.current_question) render({current: s.current_question, state: s.session, last_answer: s.last_answer});
    }catch(e){}
  }, 2500);
}
async function loadMetrics(){ const o = await call('/metrics/summary'); logMsg({metrics:o}); render(o); }
document.getElementById('url').addEventListener('keydown', e=>{ if(e.key==='Enter') start(); });
const pre = new URLSearchParams(location.search).get('url'); if (pre) document.getElementById('url').value = pre;
</script></body></html>"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--cache-dir", default=".quizagent_cache")
    a = ap.parse_args()
    serve(a.port, a.cache_dir)
