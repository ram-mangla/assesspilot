from dataclasses import dataclass, field
from typing import Any

from .normalize import fingerprint, norm_opt


@dataclass
class Opt:
    text: str
    value: str = ""
    state: Any = None      # Locator of element holding checked/selected state
    click: Any = None      # Locator to click
    checked: bool = False
    idx: int | None = None  # <select> option index


@dataclass
class Q:
    kind: str              # single | multi | select | text | textarea | number
    prompt: str
    options: list[Opt]
    answered: bool
    mode: str              # native | aria | custom | heur | select | text
    reliable: bool
    ctrl: Any              # Locator of first control
    frame: Any
    fp: str = ""
    dup: int = 0           # occurrence index among identical fingerprints on page

    def __post_init__(self):
        self.fp = fingerprint(self.prompt, [o.text for o in self.options])

    @property
    def key(self) -> str:
        return f"{self.fp}#{self.dup}"

    def selected_texts(self) -> list[str]:
        return [o.text for o in self.options if o.checked]

    def find_option(self, text: str) -> int | None:
        t = norm_opt(text)
        for i, o in enumerate(self.options):
            if norm_opt(o.text) == t:
                return i
        hits = [i for i, o in enumerate(self.options) if t and (t in norm_opt(o.text) or norm_opt(o.text) in t)]
        return hits[0] if len(hits) == 1 else None


@dataclass
class Nav:
    text: str
    action: str | None     # start | next | prev | submit | confirm | None
    loc: Any
    disabled: bool = False
    modal: bool = False


@dataclass
class Choice:
    indices: list[int] = field(default_factory=list)
    text: str | None = None
    source: str = ""
    matched: bool = True

    def texts(self, q: Q) -> list[str]:
        if q.kind in ("text", "textarea", "number"):
            return [self.text or ""]
        return [q.options[i].text for i in self.indices]


@dataclass
class Obs:
    url: str
    questions: list[Q]
    navs: list[Nav]
    text: str
    login: bool = False
    done_marker: bool = False

    @property
    def modal_navs(self):
        return [n for n in self.navs if n.modal]

    def sig(self) -> tuple:
        return (self.url.split("#")[0], tuple(q.key for q in self.questions),
                tuple((n.action, n.text, n.disabled, n.modal) for n in self.navs), hash(self.text[:300]))
