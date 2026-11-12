"""Behavior profiles: pacing and interaction style. For load / robustness testing
of your own quiz pages (think-time, typing speed, answer changes, back-and-forth)."""
import json
import random
import time
from dataclasses import dataclass, field, asdict


@dataclass
class Behavior:
    name: str = "instant"
    read_wpm: float = 0.0            # reading delay per question (0 = none)
    think: tuple = (0.0, 0.0)        # extra thinking seconds per question
    type_cps: float = 0.0            # typing speed chars/sec (0 = instant fill)
    action_gap: tuple = (0.0, 0.0)   # pause between UI actions
    change_answer_p: float = 0.0     # pick a different option first, then switch
    revisit_p: float = 0.0           # after Next, go Previous then Next again
    review_pause: tuple = (0.0, 0.0) # pause on summary/review pages
    click_jitter: bool = False       # click at random point inside element box
    speed: float = 1.0               # global time divisor (2.0 = twice as fast)

    def pause(self, rng: random.Random, rng_range: tuple, extra: float = 0.0):
        lo, hi = rng_range
        t = (rng.uniform(lo, hi) if hi > 0 else 0.0) + extra
        if t > 0:
            time.sleep(t / max(self.speed, 0.01))

    def read_time(self, prompt: str) -> float:
        if not self.read_wpm:
            return 0.0
        return len(prompt.split()) / (self.read_wpm / 60.0)


PROFILES = {
    "instant": Behavior("instant"),
    "student": Behavior("student", read_wpm=220, think=(0.8, 3.0), type_cps=5, action_gap=(0.2, 0.8),
                        change_answer_p=0.10, revisit_p=0.05, review_pause=(1, 3), click_jitter=True),
    "careful": Behavior("careful", read_wpm=160, think=(2.0, 6.0), type_cps=4, action_gap=(0.4, 1.2),
                        change_answer_p=0.20, revisit_p=0.20, review_pause=(3, 8), click_jitter=True),
    "erratic": Behavior("erratic", read_wpm=300, think=(0.1, 4.0), type_cps=8, action_gap=(0.05, 1.5),
                        change_answer_p=0.40, revisit_p=0.35, review_pause=(0, 4), click_jitter=True),
}


def load(spec: str, speed: float = 1.0) -> Behavior:
    if spec in PROFILES:
        b = Behavior(**asdict(PROFILES[spec]))
    else:
        d = json.load(open(spec))
        d = {k: tuple(v) if isinstance(v, list) else v for k, v in d.items()}
        b = Behavior(**d)
    b.speed = speed
    return b
