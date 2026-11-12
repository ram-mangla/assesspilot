import json
import re

from .model import Nav, Obs, Opt, Q
from .scanjs import SCAN_JS

# ---- nav classification ---------------------------------------------------
_BACK = re.compile(r"^(prev(ious)?|back|return|go back)\b|^[←«<]", re.I)
_START = re.compile(r"^(start|begin|attempt|take|launch|retake|re-?attempt|resume|continue (your )?attempt|let.?s go)\b", re.I)
_NEXT = re.compile(r"^(next|continue|proceed|save (&|and|&amp;) next)\b|^[→»>]|\bnext (page|question)\b", re.I)
_SUBMIT = re.compile(r"(submit|finish|finali[sz]e|turn in|end (the )?(quiz|test|exam|attempt)|complete (the )?(quiz|test|exam|attempt)|check answers|^done$)", re.I)
_CONFIRM = re.compile(r"(submit|confirm|yes|^ok$|proceed|finish|start|continue|sure|agree|end now|turn in)", re.I)
_CANCEL = re.compile(r"(cancel|^no\b|close|dismiss|return|go back|keep|not yet|stay|×)", re.I)


def classify(text: str, modal: bool) -> str | None:
    t = text.strip()
    if modal:
        if _CANCEL.search(t) and not re.search(r"submit|confirm|yes", t, re.I):
            return "cancel"
        return "confirm" if _CONFIRM.search(t) else None
    for name, rx in (("prev", _BACK), ("start", _START), ("next", _NEXT), ("submit", _SUBMIT)):
        if rx.search(t):
            return name
    return None


class GenericAdapter:
    name = "generic"
    heuristic = True

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    def match(self, page) -> bool:
        return True

    def scan_cfg(self) -> dict:
        return {"heuristic": self.heuristic}

    def frames(self, page):
        return list(page.frames)

    def build_q(self, fr, d) -> Q:
        loc = lambda uid: fr.locator(f'[data-qa="{uid}"]')
        opts = [Opt(text=o["text"], value=o.get("value", ""), checked=o.get("checked", False), idx=o.get("idx"),
                    state=loc(o["uid"]) if o.get("uid") else None, click=loc(o["click"]) if o.get("click") else None)
                for o in d["options"]]
        return Q(kind=d["kind"], prompt=d["prompt"], options=opts, answered=d["answered"], mode=d["mode"],
                 reliable=d["reliable"], ctrl=loc(d["uid"]), frame=fr)

    def observe(self, page) -> Obs:
        questions, navs, texts, login = [], [], [], False
        for fr in self.frames(page):
            try:
                res = fr.evaluate(SCAN_JS, self.scan_cfg())
            except Exception:
                continue
            questions += [self.build_q(fr, d) for d in res["questions"]]
            loc = lambda uid, fr=fr: fr.locator(f'[data-qa="{uid}"]')
            navs += [Nav(n["text"], classify(n["text"], n["modal"]), loc(n["uid"]), n["disabled"], n["modal"]) for n in res["navs"]]
            texts.append(res["text"])
            login = login or res["hasPassword"]
        seen = {}
        for q in questions:
            q.dup = seen.get(q.fp, 0)
            seen[q.fp] = q.dup + 1
        obs = Obs(url=page.url, questions=questions, navs=navs, text=" ".join(texts), login=login)
        self.post(page, obs)
        return obs

    def post(self, page, obs: Obs):
        pass


class MoodleAdapter(GenericAdapter):
    """Moodle quiz (mod_quiz). Written against Moodle 4.x DOM: .que containers, .qtext prompts,
    input[name=next], 'Finish attempt ...' -> summary -> 'Submit all and finish' modal."""
    name = "moodle"
    heuristic = False

    def match(self, page) -> bool:
        try:
            return bool(page.evaluate("() => !!(window.M && window.M.cfg && window.M.cfg.wwwroot)"))
        except Exception:
            return False

    def scan_cfg(self):
        return {"qsel": ".que", "promptSel": ".qtext", "stripSel": ".answernumber,.accesshide,.sr-only,.sr-only-focusable",
                "heuristic": False}

    def post(self, page, obs: Obs):
        if "/mod/quiz/review.php" in obs.url:
            obs.done_marker = True

    def collect_result(self, page, quiz_url: str) -> str:
        """Review may be disallowed for students; the quiz's own page lists grade / final grade."""
        try:
            page.goto(quiz_url, wait_until="domcontentloaded", timeout=30000)
            return page.evaluate("() => document.body.innerText")[:4000]
        except Exception:
            return ""


class ConfigAdapter(GenericAdapter):
    """Declarative profile for a custom site. See README for the schema."""
    name = "config"

    def __init__(self, config: dict):
        super().__init__(config)
        self.name = "config:" + config.get("name", "unnamed")

    def match(self, page) -> bool:
        rx = (self.config.get("match") or {}).get("url")
        return bool(re.search(rx, page.url)) if rx else True

    def scan_cfg(self):
        q = self.config.get("question") or {}
        return {"qsel": q.get("container"), "promptSel": q.get("prompt"), "optionSel": q.get("option"),
                "optionTextSel": q.get("option_text"), "selectedSel": q.get("selected"), "multi": q.get("multi"),
                "stripSel": q.get("strip"), "heuristic": self.config.get("heuristic", False)}

    def frames(self, page):
        sel = self.config.get("frame")
        if sel:
            try:
                return [page.locator(sel).first.element_handle().content_frame()]
            except Exception:
                return []
        return list(page.frames)

    def post(self, page, obs: Obs):
        nav = self.config.get("nav") or {}
        for action, sels in nav.items():
            sels = [sels] if isinstance(sels, str) else sels
            for sel in sels:
                hit = None
                for fr in self.frames(page):
                    try:
                        loc = fr.locator(sel).first
                        if loc.count() and loc.is_visible():
                            hit = Nav(sel, action, loc, disabled=not loc.is_enabled(), modal=(action == "confirm"))
                            break
                    except Exception:
                        continue
                if hit:
                    obs.navs = [n for n in obs.navs if n.action != action] + [hit]
                    break
        for sel in self.config.get("done") or []:
            for fr in self.frames(page):
                try:
                    if fr.locator(sel).first.is_visible():
                        obs.done_marker = True
                except Exception:
                    pass


class LearnedAdapter(GenericAdapter):
    """Dynamic adapter driven by evolved selectors from SelfLearningEngine."""
    name = "learned"
    heuristic = True

    def __init__(self, pattern):
        super().__init__()
        self.pattern = pattern
        self.name = f"learned:{pattern.site_key}"

    def scan_cfg(self):
        return {
            "qsel": self.pattern.q_selector,
            "promptSel": self.pattern.prompt_selector,
            "optionSel": self.pattern.option_selector,
            "optionTextSel": self.pattern.option_text_selector,
            "selectedSel": self.pattern.selected_selector,
            "heuristic": True,
        }


REGISTRY = {"moodle": MoodleAdapter, "generic": GenericAdapter}


def detect(page, cache=None, forced: str | None = None, config: dict | None = None, learner=None):
    if config:
        a = ConfigAdapter(config)
        return a
    if forced and forced != "auto":
        return REGISTRY[forced]()
    if learner:
        pat = learner.get_learned_dom(page.url)
        if pat and pat.confidence >= 0.6:
            return LearnedAdapter(pat)
    cached = cache.get_adapter(page.url) if cache else None
    if cached in REGISTRY:
        a = REGISTRY[cached]()
        if a.match(page):
            return a
        cache.drop_adapter(page.url)
    for name in ("moodle",):
        a = REGISTRY[name]()
        if a.match(page):
            return a
    return GenericAdapter()
