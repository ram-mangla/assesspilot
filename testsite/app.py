"""Local quiz sites in many formats. Server-side grading so tests can assert what was really
submitted. Run: python testsite/app.py [port]"""
import json
import re
import sys
import uuid

from flask import Flask, jsonify, make_response, redirect, render_template_string, request

app = Flask(__name__)

BANK = [
    {"id": 1, "type": "single", "text": "Which HTTP method is idempotent?", "options": ["POST", "PUT", "PATCH", "CONNECT"], "answer": ["PUT"]},
    {"id": 2, "type": "multi", "text": "Select all prime numbers.", "options": ["2", "3", "4", "9"], "answer": ["2", "3"]},
    {"id": 3, "type": "single", "text": "The TCP handshake uses three packets.", "options": ["True", "False"], "answer": ["True"]},
    {"id": 4, "type": "select", "text": "Capital of France?", "options": ["Berlin", "Paris", "Rome"], "answer": ["Paris"]},
    {"id": 5, "type": "text", "text": "Chemical symbol for gold?", "answer": ["Au"]},
    {"id": 6, "type": "number", "text": "What is 7 x 6?", "answer": ["42"]},
    {"id": 7, "type": "textarea", "text": 'Name one HTTP status code for "Not Found".', "answer": ["404"]},
]
MATCH = [{"id": 8, "type": "match", "text": "Match each city with its country.",
          "rows": [("Tokyo", "Japan"), ("Cairo", "Egypt")], "options": ["Japan", "Egypt", "Peru"]}]
FORM_BANK = BANK + MATCH
RESULTS: dict[str, dict] = {}
ATT: dict[str, dict] = {}


def n(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def grade(answers: dict[str, list[str]], bank=None):
    bank = bank or FORM_BANK
    score = 0
    for q in bank:
        if q["type"] == "match":
            ok = all(n((answers.get(f"{q['id']}_{i}") or [""])[0]) == n(c) for i, (_, c) in enumerate(q["rows"]))
        else:
            ok = sorted(map(n, answers.get(str(q["id"]), []))) == sorted(map(n, q["answer"]))
        score += ok
    return score, len(bank)


def record(site, answers, bank=None):
    s, t = grade(answers, bank)
    RESULTS[site] = {"answers": answers, "score": s, "total": t}
    return s, t


def parse_form(form, layout="std"):
    ans = {}
    for k in form:
        vals = [v for v in form.getlist(k) if v != ""]
        m = re.match(r"^q(\d+)(?:_(\w+))?$", k)
        if not m:
            continue
        qid, sub = m.groups()
        q = next((x for x in FORM_BANK if str(x["id"]) == qid), None)
        if q and q["type"] == "multi" and sub is not None:      # alt layout: one name per option
            ans.setdefault(qid, []).extend(vals)
        elif q and q["type"] == "match":
            ans[f"{qid}_{sub}"] = vals
        else:
            ans[qid] = vals
    return ans


CSS = """<style>body{font-family:system-ui;max-width:760px;margin:24px auto;padding:0 12px}
.q{margin:18px 0;padding:10px;border:1px solid #ddd;border-radius:6px} button,.btn{padding:8px 16px;margin:4px;cursor:pointer}
.opts label{display:block;margin:4px 0} .banner{background:#eef;padding:6px;margin-bottom:10px}</style>"""


def render_questions(bank, layout="std"):
    out = []
    for q in bank:
        i = q["id"]
        if layout == "alt":
            out.append(f"<h3>{i}. {q['text']}</h3>")
        t = q["type"]
        body = ""
        if t in ("single", "multi"):
            items = []
            for k, o in enumerate(q["options"]):
                if t == "single":
                    inp = f'<input type="radio" name="q{i}" value="{o}">'
                elif layout == "alt":
                    inp = f'<input type="checkbox" name="q{i}_{k}" value="{o}">'
                else:
                    inp = f'<input type="checkbox" name="q{i}" value="{o}">'
                items.append(f"<li><label>{inp} {o}</label></li>" if layout == "alt" else f"<label>{inp} {o}</label>")
            body = "<ul class=opts>" + "".join(items) + "</ul>" if layout == "alt" else "<div class=opts>" + "".join(items) + "</div>"
        elif t == "select":
            body = f'<select name="q{i}"><option value="">-- choose --</option>' + "".join(f"<option>{o}</option>" for o in q["options"]) + "</select>"
        elif t == "text":
            body = f'<input type="text" name="q{i}" placeholder="Your answer">'
        elif t == "number":
            body = f'<input type="number" name="q{i}">'
        elif t == "textarea":
            body = f'<textarea name="q{i}" rows="2"></textarea>'
        elif t == "match":
            rows = "".join(f'<tr><td>{c}</td><td><select name="q{i}_{k}"><option value="">Choose...</option>' +
                           "".join(f"<option>{o}</option>" for o in q["options"]) + "</select></td></tr>" for k, (c, _) in enumerate(q["rows"]))
            body = f"<table>{rows}</table>"
        if layout == "alt":
            out.append(body)
        else:
            out.append(f'<div class="q"><p class="qt">{i}. {q["text"]}</p>{body}</div>')
    return "\n".join(out)


def result_page(site, s, t, extra=""):
    return f'<!doctype html><title>Results</title>{CSS}<h1>Quiz results</h1><p id="score">Score: {s} / {t} ({round(100 * s / t)}%)</p>{extra}<p><a class="btn" href="/{site}">Retake quiz</a></p>'


# ---------------------------------------------------------------- single page form (+ alt layout, + iframe)
@app.route("/single", methods=["GET", "POST"])
def single():
    layout = request.args.get("layout", "std")
    if request.method == "POST":
        s, t = record("single", parse_form(request.form))
        if request.args.get("noscore"):
            return f"<!doctype html><title>Thanks</title>{CSS}<h1>Thank you</h1><p>Your response has been recorded.</p>"
        return result_page("single", s, t)
    return render_template_string("""<!doctype html><title>Single page quiz</title>{{css|safe}}
<h1>Networking basics</h1>
<form method="post" action="/single?layout={{layout}}{% if noscore %}&noscore=1{% endif %}">{{body|safe}}<button type="submit">Submit Quiz</button></form>""",
                                  css=CSS, layout=layout, noscore=request.args.get('noscore'), body=render_questions(FORM_BANK, layout))


@app.route("/iframe")
def iframe():
    return f'<!doctype html><title>Embedded</title>{CSS}<div class="banner">Course portal header</div><iframe src="/single" style="width:100%;height:1400px;border:0"></iframe>'


# ---------------------------------------------------------------- paged, Moodle-like (prev/next, summary, confirm modal)
@app.route("/paged")
def paged_start():
    return f'<!doctype html><title>Paged quiz</title>{CSS}<h1>Paged quiz</h1><p>Attempts allowed: 1</p><form method="post" action="/paged/start"><button type="submit">Attempt quiz</button></form>'


@app.route("/paged/start", methods=["POST"])
def paged_new():
    aid = uuid.uuid4().hex[:8]
    ATT[aid] = {"answers": {}}
    return redirect(f"/paged/a/{aid}/1")


@app.route("/paged/a/<aid>/<page>", methods=["GET", "POST"])
def paged_page(aid, page):
    at = ATT[aid]
    if request.method == "POST":
        for k, v in parse_form(request.form).items():
            at["answers"][k] = v
        cur = int(request.form["_page"])
        if "prev" in request.form:
            return redirect(f"/paged/a/{aid}/{cur - 1}")
        return redirect(f"/paged/a/{aid}/{cur + 1 if cur < len(BANK) else 'summary'}")
    if page == "summary":
        rows = "".join(f"<tr><td>{q['id']}</td><td>{'Answer saved' if str(q['id']) in at['answers'] else 'Not yet answered'}</td></tr>" for q in BANK)
        return render_template_string("""<!doctype html><title>Summary</title>{{css|safe}}<h1>Summary of attempt</h1>
<table border=1 cellpadding=4><tr><th>Question</th><th>Status</th></tr>{{rows|safe}}</table>
<a href="/paged/a/{{aid}}/{{last}}">Return to attempt</a>
<form id="f" method="post" action="/paged/a/{{aid}}/submit"><button type="button" id="openbtn">Submit all and finish</button></form>
<div id="m" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.5)"><div style="background:#fff;margin:15% auto;padding:20px;width:360px" role="dialog">
<p>Once you submit, you will no longer be able to change your answers.</p>
<button type="button" id="go">Submit all and finish</button><button type="button" id="cancel">Cancel</button></div></div>
<script>openbtn.onclick=()=>m.style.display='block';cancel.onclick=()=>m.style.display='none';go.onclick=()=>f.submit();</script>""",
                                      css=CSS, rows=rows, aid=aid, last=len(BANK))
    p = int(page)
    q = BANK[p - 1]
    nav_prev = '<button type="submit" name="prev" value="1">Previous page</button>' if p > 1 else ""
    nav_next = ('<button type="submit" name="next" value="1">Next page</button>' if p < len(BANK)
                else f'<a class="btn" href="/paged/a/{aid}/summary" onclick="document.forms[0].requestSubmit(document.querySelector(\'[name=save]\'));return false;">Finish attempt ...</a>')
    return render_template_string("""<!doctype html><title>Question {{p}}</title>{{css|safe}}
<div class="banner">Quiz navigation: Question {{p}} of {{n}}</div>
<form method="post" action="/paged/a/{{aid}}/{{p}}"><input type="hidden" name="_page" value="{{p}}">
{{body|safe}}<div>{{prev|safe}}{{next|safe}}</div>
<button type="submit" name="save" value="1" style="display:none">save</button></form>""",
                                  css=CSS, p=p, n=len(BANK), aid=aid, body=render_questions([q]), prev=nav_prev, next=nav_next)


@app.route("/paged/a/<aid>/submit", methods=["POST"])
def paged_submit(aid):
    s, t = record("paged", ATT[aid]["answers"], BANK)
    return result_page("paged", s, t)


# ---------------------------------------------------------------- SPA: async load, one question/screen, div/aria options, modal confirm
@app.route("/api/questions")
def api_q():
    return jsonify([{k: v for k, v in q.items() if k != "answer"} for q in BANK])


@app.route("/api/submit/<site>", methods=["POST"])
def api_submit(site):
    ans = request.get_json()["answers"]
    s, t = record(site, ans, BANK)
    return jsonify({"score": s, "total": t})


SPA = """<!doctype html><title>SPA quiz</title>{{css|safe}}
<style>.opt{padding:10px;margin:6px 0;border:1px solid #999;border-radius:6px;cursor:pointer}.opt.selected{background:#cde;border-color:#06c}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.5);display:none}.box{background:#fff;margin:15% auto;padding:20px;width:340px}
button:disabled{opacity:.4}</style>
<div id="app">Loading...</div>
<div id="modal" class="modal"><div class="box"><p>Are you sure you want to submit?</p><button id="yes">Yes, submit</button><button id="no">Cancel</button></div></div>
<script>
const P=new URLSearchParams(location.search),MODE=P.get('mode')||'div',DELAY=+(P.get('delay')||0),SITE=P.get('site')||'spa';
let Q=[],i=0,A={};
const app=document.getElementById('app');
async function boot(){await new Promise(r=>setTimeout(r,DELAY));Q=await (await fetch('/api/questions')).json();render();}
const answered=q=>(A[q.id]||[]).length>0;
function render(){
  const q=Q[i];let h=`<div class="qbox"><h2>Question ${i+1} of ${Q.length}</h2><p class="stem">${q.text}</p><div class="opts" ${MODE==='aria'&&(q.type==='single'||q.type==='multi')?`role="${q.type==='multi'?'group':'radiogroup'}" aria-label="${q.text.replace(/"/g,'&quot;')}"`:''}>`;
  if(q.type==='single'||q.type==='multi'){
    q.options.forEach((o,k)=>{const on=(A[q.id]||[]).includes(o);
      if(MODE==='aria')h+=`<div class="opt ${on?'selected':''}" role="${q.type==='multi'?'checkbox':'radio'}" aria-checked="${on}" tabindex="0" data-v="${o}">${o}</div>`;
      else h+=`<div class="opt ${on?'selected':''}" data-v="${o}">${o}</div>`;});
  } else if(q.type==='select'){h+=`<select id="sel"><option value="">Select...</option>${q.options.map(o=>`<option ${(A[q.id]||[])[0]===o?'selected':''}>${o}</option>`).join('')}</select>`;}
  else if(q.type==='textarea'){h+=`<textarea id="txt" rows="2">${(A[q.id]||[''])[0]}</textarea>`;}
  else {h+=`<input id="txt" type="${q.type==='number'?'number':'text'}" placeholder="Type your answer" value="${(A[q.id]||[''])[0]}">`;}
  h+=`</div><div class="nav"><button id="prev" ${i==0?'disabled':''}>Previous</button>`+(i<Q.length-1?`<button id="next">Next</button>`:`<button id="submit">Submit</button>`)+`</div></div>`;
  app.innerHTML=h;upd();
  app.querySelectorAll('.opt').forEach(el=>el.onclick=()=>{const v=el.dataset.v;
    if(q.type==='multi'){const s=new Set(A[q.id]||[]);s.has(v)?s.delete(v):s.add(v);A[q.id]=[...s];}else A[q.id]=[v];render();});
  const sel=document.getElementById('sel');if(sel)sel.onchange=()=>{A[q.id]=sel.value?[sel.value]:[];upd();};
  const t=document.getElementById('txt');if(t)t.oninput=()=>{A[q.id]=t.value?[t.value]:[];upd();};
  document.getElementById('prev').onclick=()=>{i--;render();};
  const nx=document.getElementById('next');if(nx)nx.onclick=()=>{i++;render();};
  const sb=document.getElementById('submit');if(sb)sb.onclick=()=>{document.getElementById('modal').style.display='block';};
}
function upd(){const q=Q[i];const b=document.getElementById('next')||document.getElementById('submit');if(b)b.disabled=!answered(q);}
document.getElementById('no').onclick=()=>document.getElementById('modal').style.display='none';
document.getElementById('yes').onclick=async()=>{document.getElementById('modal').style.display='none';
  const r=await (await fetch('/api/submit/'+SITE,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({answers:Object.fromEntries(Object.entries(A).map(([k,v])=>[k,v]))})})).json();
  app.innerHTML=`<div id="result"><h2>Quiz complete</h2><p>Score: ${r.score} / ${r.total}</p><button id="retake" onclick="location.reload()">Retake quiz</button></div>`;};
boot();
</script>"""


@app.route("/spa")
def spa():
    return render_template_string(SPA, css=CSS)


# ---------------------------------------------------------------- shadow DOM widget
@app.route("/shadow")
def shadow():
    body = render_questions(FORM_BANK).replace("`", "").replace("\\", "")
    return render_template_string("""<!doctype html><title>Shadow quiz</title>{{css|safe}}<h1>Web component quiz</h1><quiz-widget></quiz-widget>
<script>
class QW extends HTMLElement{connectedCallback(){const r=this.attachShadow({mode:'open'});
 r.innerHTML=`<style>.q{margin:14px 0;padding:8px;border:1px solid #ccc} label{display:block}</style><form id="f">{{body|safe}}<button type="button" id="go">Submit quiz</button></form><div id="res"></div>`;
 r.getElementById('go').onclick=async()=>{const fd=new FormData(r.getElementById('f'));const body=new URLSearchParams();for(const [k,v] of fd)body.append(k,v);
  const t=await (await fetch('/shadow/submit',{method:'POST',body})).text();r.getElementById('res').innerHTML=t;r.getElementById('f').style.display='none';};}}
customElements.define('quiz-widget',QW);
</script>""", css=CSS, body=body)


@app.route("/shadow/submit", methods=["POST"])
def shadow_submit():
    s, t = record("shadow", parse_form(request.form))
    return f'<p id="score">Score: {s} / {t}</p><a href="/shadow">Retake quiz</a>'


# ---------------------------------------------------------------- timed: begin button, ticking timer, native confirm()
@app.route("/timed")
def timed():
    return render_template_string("""<!doctype html><title>Timed test</title>{{css|safe}}
<div id="timer" class="banner" style="display:none">Time left: 09:59</div>
<div id="intro"><h1>Final assessment</h1><p>You have 10 minutes.</p><button id="begin">Begin Test</button></div>
<div id="box" style="display:none"><form id="f">{{body|safe}}<button type="button" id="fin">Finish Test</button></form></div><div id="out"></div>
<script>
let s=599;begin.onclick=()=>{intro.style.display='none';box.style.display='block';timer.style.display='block';
 setInterval(()=>{s--;timer.textContent='Time left: 0'+Math.floor(s/60)+':'+String(s%60).padStart(2,'0');},1000);};
fin.onclick=async()=>{if(!confirm('Submit your test?'))return;const b=new URLSearchParams(new FormData(f));
 const t=await (await fetch('/timed/submit',{method:'POST',body:b})).text();box.style.display='none';out.innerHTML=t;};
</script>""", css=CSS, body=render_questions(FORM_BANK))


@app.route("/timed/submit", methods=["POST"])
def timed_submit():
    s, t = record("timed", parse_form(request.form))
    return f'<h2>Test submitted</h2><p id="score">Your grade: {s} / {t}</p><a href="/timed">Retake</a>'


# ---------------------------------------------------------------- login-gated quiz
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("username") == "demo" and request.form.get("password") == "demo123":
            r = make_response(redirect("/secure"))
            r.set_cookie("sess", "ok")
            return r
        return f"{CSS}<p>Invalid login</p>", 401
    return f'<!doctype html><title>Login</title>{CSS}<h1>Sign in</h1><form method="post"><input name="username" placeholder="Username"><input name="password" type="password" placeholder="Password"><button type="submit">Log in</button></form>'


@app.route("/secure", methods=["GET", "POST"])
def secure():
    if request.cookies.get("sess") != "ok":
        return redirect("/login")
    if request.method == "POST":
        s, t = record("secure", parse_form(request.form))
        return result_page("secure", s, t)
    return render_template_string("""<!doctype html><title>Secure quiz</title>{{css|safe}}<h1>Members quiz</h1>
<form method="post" action="/secure">{{body|safe}}<button type="submit">Submit Quiz</button></form>""", css=CSS, body=render_questions(FORM_BANK))


# ---------------------------------------------------------------- Moodle-shaped DOM fixture (hand-written from Moodle 4.x markup; NOT real Moodle)
@app.route("/moodle-like", methods=["GET", "POST"])
def moodle_like():
    if request.method == "POST":
        f, ans = request.form, {}
        ans["1"] = [BANK[0]["options"][int(f["q1:1_answer"])]] if f.get("q1:1_answer") else []
        ans["2"] = [o for k, o in enumerate(BANK[1]["options"]) if f.get(f"q2:1_choice{k}")]
        ans["3"] = [BANK[2]["options"][int(f["q3:1_answer"])]] if f.get("q3:1_answer") else []
        for k in range(2):
            v = f.get(f"q4:1_sub{k}")
            ans[f"8_{k}"] = [MATCH[0]["options"][int(v) - 1]] if v else []
        ans["5"] = [f.get("q5:1_answer", "")]
        s, t = grade(ans, [BANK[0], BANK[1], BANK[2], MATCH[0], BANK[4]])
        RESULTS["moodle_like"] = {"answers": ans, "score": s, "total": t}
        return f"<!doctype html><title>Quiz review</title><h1>Review</h1><p>Grade: {s} / {t}</p>"
    def ans(n, opts, typ, multi=False):
        rows = ""
        for k, o in enumerate(opts):
            inp = (f'<input type="checkbox" name="q{n}:1_choice{k}" value="1" id="q{n}:1_choice{k}" aria-labelledby="q{n}:1_choice{k}_label">' if multi else
                   f'<input type="radio" name="q{n}:1_answer" value="{k}" id="q{n}:1_answer{k}" aria-labelledby="q{n}:1_answer{k}_label">')
            lid = f"q{n}:1_{'choice' if multi else 'answer'}{k}_label"
            rows += f'<div class="r{k % 2}">{inp}<div class="d-flex w-auto"><span class="answernumber">{chr(97 + k)}. </span><div id="{lid}" class="flex-fill ml-1"><p>{o}</p></div></div></div>'
        return f'<div class="ablock"><div class="prompt">Select {"one or more" if multi else "one"}:</div><div class="answer">{rows}</div></div>'
    q1 = f'<div id="question-1-1" class="que multichoice deferredfeedback notyetanswered"><div class="info"><h3 class="no">Question <span class="qno">1</span></h3><div class="state">Not yet answered</div></div><div class="content"><div class="formulation clearfix"><div class="qtext"><p>{BANK[0]["text"]}</p></div>{ans(1, BANK[0]["options"], "r")}</div></div></div>'
    q2 = f'<div id="question-1-2" class="que multichoice deferredfeedback notyetanswered"><div class="info"><h3 class="no">Question <span class="qno">2</span></h3></div><div class="content"><div class="formulation clearfix"><div class="qtext"><p>{BANK[1]["text"]}</p></div>{ans(2, BANK[1]["options"], "c", True)}</div></div></div>'
    q3 = f'<div id="question-1-3" class="que truefalse deferredfeedback notyetanswered"><div class="info"><h3 class="no">Question <span class="qno">3</span></h3></div><div class="content"><div class="formulation clearfix"><div class="qtext"><p>{BANK[2]["text"]}</p></div>{ans(3, ["True", "False"], "r")}</div></div></div>'
    mrows = "".join(f'<tr class="r{k}"><td class="text"><p>{c}</p></td><td class="control"><label class="accesshide" for="m{k}">Answer for {c}</label><select id="m{k}" name="q4:1_sub{k}" class="select custom-select"><option selected value="">Choose...</option>' + "".join(f'<option value="{j + 1}">{o}</option>' for j, o in enumerate(MATCH[0]["options"])) + "</select></td></tr>" for k, (c, _) in enumerate(MATCH[0]["rows"]))
    q4 = f'<div id="question-1-4" class="que match deferredfeedback notyetanswered"><div class="info"><h3 class="no">Question <span class="qno">4</span></h3></div><div class="content"><div class="formulation clearfix"><div class="qtext"><p>{MATCH[0]["text"]}</p></div><table class="answer"><tbody>{mrows}</tbody></table></div></div></div>'
    q5 = f'<div id="question-1-5" class="que shortanswer deferredfeedback notyetanswered"><div class="info"><h3 class="no">Question <span class="qno">5</span></h3></div><div class="content"><div class="formulation clearfix"><div class="qtext"><p>{BANK[4]["text"]}</p></div><div class="ablock"><span class="answer"><label class="accesshide" for="q5:1_answer">Answer</label><input type="text" name="q5:1_answer" id="q5:1_answer" size="30" class="form-control d-inline"></span></div></div></div></div>'
    return f'''<!doctype html><html><head><title>Moodle-like quiz</title><script>var M={{cfg:{{wwwroot:"http://127.0.0.1:5055"}}}};</script>{CSS}</head>
<body id="page-mod-quiz-attempt" class="path-mod-quiz"><form method="post" id="responseform"><div>{q1}{q2}{q3}{q4}{q5}</div>
<div class="submitbtns"><input type="submit" name="next" value="Finish attempt ..." class="mod_quiz-next-nav btn btn-primary"></div></form></body></html>'''


# ---------------------------------------------------------------- hub: non-Moodle site with nested navigation + junk links
@app.route("/hub")
def hub():
    return f'<!doctype html><title>Learning portal</title>{CSS}<h1>Welcome</h1><nav><a href="/hub/forum">Forum</a> <a href="/hub/profile">My profile</a> <a href="/hub/logout">Log out</a> <a href="/hub/courses">My courses</a></nav>'


@app.route("/hub/courses")
def hub_courses():
    return f'<!doctype html><title>Courses</title>{CSS}<h1>My courses</h1><ul><li><a href="/hub/course/networking">Networking 101</a></li><li><a href="/hub/course/empty">Empty course</a></li></ul>'


@app.route("/hub/course/<name>")
def hub_course(name):
    if name == "empty":
        return f"<!doctype html><title>Empty</title>{CSS}<h1>Empty course</h1><p>Nothing here.</p>"
    return f'<!doctype html><title>Networking 101</title>{CSS}<h1>Networking 101</h1><ul><li><a href="/hub/course/networking/syllabus">Syllabus</a></li><li><a href="/single">Networking basics quiz</a></li><li><a href="/hub/logout">Sign out</a></li></ul>'


@app.route("/hub/<path:x>")
def hub_misc(x):
    return f"<!doctype html><title>{x}</title>{CSS}<h1>{x}</h1>"


# ---------------------------------------------------------------- test control
@app.route("/_results/<site>")
def results(site):
    return jsonify(RESULTS.get(site) or {})


@app.route("/_reset")
def reset():
    RESULTS.clear()
    return "ok"


@app.route("/_key.json")
def key():
    ent = [{"match": q["text"], "answer": q["answer"]} for q in BANK]
    for q in MATCH:
        ent += [{"match": f"exact:{c}", "answer": v} for c, v in q["rows"]]
    return jsonify({"answers": ent})


if __name__ == "__main__":
    app.run("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 5055, threaded=True)
