"""Find quizzes starting from any URL: log in if needed, then best-first crawl of same-origin links."""
import heapq
import re
import time
from dataclasses import dataclass
from urllib.parse import urldefrag, urlsplit

LINKS_JS = r"""() => {
  const out = [], seen = new Set();
  document.querySelectorAll('a[href]').forEach(a => {
    const r = a.getBoundingClientRect(), cs = getComputedStyle(a);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    const href = a.href; if (!/^https?:/.test(href) || seen.has(href)) return; seen.add(href);
    out.push({href, text: (a.innerText || a.getAttribute('aria-label') || a.title || '').replace(/\s+/g, ' ').trim().slice(0, 120)});
  });
  return out;
}"""

STRONG = re.compile(r"/mod/quiz/view\.php|/quiz/view|/assessments?/\w+|/exams?/\w+|/tests?/\w+|/quiz(zes)?/\w+", re.I)
QUIZY = re.compile(r"quiz|test|exam|assessment|attempt", re.I)
EXPLORE = re.compile(r"/mod/quiz/index\.php|/course/view\.php|/my/|dashboard|my courses|courses?\b|assessments?\b|quizzes|exams?\b|tests?\b", re.I)
AVOID = re.compile(r"log ?out|sign ?out|delete|remove|profile|preferences|settings|/admin|forum|calendar|message|grade|participants|badges|/user/|/login/(forgot|signup)|mailto|download|\.(pdf|zip|png|jpg)$", re.I)
LOGIN_LINK = re.compile(r"^(log ?in|sign ?in)$|/login/?(index\.php)?$", re.I)


@dataclass
class Found:
    url: str
    title: str
    page_title: str = ""


def score(href: str, text: str) -> int:
    s = f"{href} {text}"
    if AVOID.search(s):
        return -1
    if STRONG.search(href):
        return 100
    sc = 0
    if QUIZY.search(text):
        sc += 40
    if QUIZY.search(href):
        sc += 20
    if EXPLORE.search(s):
        sc += 15
    return sc


class Discoverer:
    def __init__(self, agent, page, ctx):
        self.a, self.page, self.ctx = agent, page, ctx
        self.log: list[str] = []

    def _go(self, url):
        self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        self.a.settle(self.page)
        time.sleep(0.6)           # dashboards often fill in after load
        self.a.settle(self.page)

    def _links(self):
        try:
            return self.page.evaluate(LINKS_JS)
        except Exception:
            return []

    def _ensure_login(self, start_url) -> None:
        from .adapters import GenericAdapter
        ad = GenericAdapter()
        for _ in range(3):
            obs = ad.observe(self.page)
            if obs.login:
                self.log.append(f"login form at {obs.url}")
                self.a.login(self.page, self.ctx, start_url)
                return
            ll = [l for l in self._links() if LOGIN_LINK.search(l["text"].strip()) or LOGIN_LINK.search(urlsplit(l["href"]).path)]
            if ll and self.a.creds:
                self.log.append(f"following login link {ll[0]['href']}")
                self._go(ll[0]["href"])
                continue
            return

    def find(self, start_url, budget=25, max_depth=3, stop_at_first=False) -> list[Found]:
        from .adapters import GenericAdapter
        origin = "{0.scheme}://{0.netloc}".format(urlsplit(start_url))
        self._go(start_url)
        self._ensure_login(start_url)
        found: dict[str, Found] = {}
        visited: set[str] = {urldefrag(self.page.url)[0]}
        pq: list = []
        n = [0]
        texts: dict[str, str] = {}

        def check_here() -> bool:
            """Is the current page a quiz entry (questions, or an attempt/start button on a quiz-ish page)?"""
            obs = GenericAdapter().observe(self.page)
            starts = [x for x in obs.navs if x.action == "start" and re.match(
                r"^(start|begin|attempt|take|launch|retake|re-?attempt|resume|continue (your )?attempt)", x.text, re.I)]
            path = urlsplit(self.page.url).path
            quizlike = any(q.kind in ("single", "multi") and len(q.options) >= 2 for q in obs.questions) or len(obs.questions) >= 3
            if quizlike or (starts and (QUIZY.search(path) or any(QUIZY.search(x.text) for x in starts))):
                u = urldefrag(self.page.url)[0]
                found[u] = Found(u, texts.get(u) or self.page.title() or u, self.page.title())
                return True
            return False

        def expand(depth: int):
            self.log.append(f"scan d{depth} {self.page.url}")
            if depth >= max_depth:
                return
            for l in self._links():
                h = urldefrag(l["href"])[0]
                if not h.startswith(origin) or h in visited:
                    continue
                sc = score(h, l["text"])
                if sc < 0:
                    continue
                if l["text"]:
                    texts.setdefault(h, l["text"])
                if sc >= 100:
                    found.setdefault(h, Found(h, l["text"] or h))
                elif sc > 0:
                    n[0] += 1
                    heapq.heappush(pq, (-sc, n[0], h, depth + 1))

        if check_here():                      # landed directly on a quiz
            return list(found.values())
        expand(0)
        while pq and len(visited) <= budget and not (stop_at_first and found):
            _, _, url, depth = heapq.heappop(pq)
            if url in visited:
                continue
            visited.add(url)
            try:
                self._go(url)
            except Exception as e:
                self.log.append(f"skip {url}: {type(e).__name__}")
                continue
            if not self.page.url.startswith(origin):
                continue
            if check_here():
                continue
            expand(depth)
        return list(found.values())
