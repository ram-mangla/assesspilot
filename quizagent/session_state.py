"""Authoritative state machine for one browser session. One state at a time; conflicting
operations are refused from disallowed states instead of being silently attempted."""
from __future__ import annotations

import threading
import time
import uuid
from contextlib import contextmanager

IDLE = "idle"
BROWSER_STARTING = "browser_starting"
BROWSER_READY = "browser_ready"
NAVIGATING = "navigating"
PAGE_LOADING = "page_loading"
AUTHENTICATION_REQUIRED = "authentication_required"
QUIZ_DETECTED = "quiz_detected"
ATTEMPT_START_PENDING = "attempt_start_pending"
ATTEMPT_ACTIVE = "attempt_active"
QUESTION_DETECTED = "question_detected"
ANSWERING = "answering"
ANSWER_READY = "answer_ready"
ANSWER_APPLYING = "answer_applying"
ANSWER_SELECTED = "answer_selected"
ANSWER_SAVING = "answer_saving"
ANSWER_SAVED = "answer_saved"
MOVING_NEXT = "moving_next"
MOVING_PREVIOUS = "moving_previous"
REVIEWING = "reviewing"
SUBMISSION_PENDING = "submission_pending"
SUBMITTING = "submitting"
SUBMITTED = "submitted"
RESULTS_AVAILABLE = "results_available"
PAUSED = "paused"
STOPPED = "stopped"
ERROR = "error"

# states in which quiz/question controls may act on the page
QUIZ_READY = frozenset({QUIZ_DETECTED, ATTEMPT_ACTIVE, QUESTION_DETECTED, ANSWER_READY, ANSWER_SELECTED,
                        ANSWER_SAVED, PAUSED, REVIEWING, AUTHENTICATION_REQUIRED, BROWSER_READY})
NAV_ALLOWED = frozenset({BROWSER_READY, PAGE_LOADING, QUIZ_DETECTED, ATTEMPT_ACTIVE, QUESTION_DETECTED,
                         ANSWER_READY, ANSWER_SELECTED, ANSWER_SAVED, PAUSED, REVIEWING,
                         AUTHENTICATION_REQUIRED, RESULTS_AVAILABLE, ERROR})
# question navigation is refused while paused or stopped: the run is not allowed to act on the page
MOVE_ALLOWED = QUIZ_READY - {PAUSED}

# every state a long operation may legitimately start from
_OPEN = frozenset({BROWSER_READY, QUIZ_DETECTED, ATTEMPT_ACTIVE, QUESTION_DETECTED, ANSWER_READY,
                   ANSWER_SELECTED, ANSWER_SAVED, PAUSED, REVIEWING, AUTHENTICATION_REQUIRED, SUBMISSION_PENDING,
                   ATTEMPT_START_PENDING})


class StateConflict(RuntimeError):
    """An operation was requested that the current state forbids."""


class SessionState:
    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.lock = threading.RLock()
        self._state = IDLE
        self._since = time.time()
        self._history: list[tuple[str, float, str]] = []
        self.last_error: str | None = None
        self.command_seq = 0

    @property
    def state(self) -> str:
        return self._state

    def set(self, state: str, reason: str = "") -> str:
        with self.lock:
            if state != self._state:
                self._history.append((state, time.time(), reason))
                del self._history[:-50]
                self._state, self._since = state, time.time()
            if state == ERROR:
                self.last_error = reason or self.last_error
            return self._state

    def snapshot(self) -> dict:
        with self.lock:
            return {"session_id": self.session_id, "state": self._state,
                    "since": round(self._since, 3), "s": round(time.time() - self._since, 1),
                    "last_error": self.last_error,
                    "history": [{"state": s, "reason": r} for s, _, r in self._history[-10:]]}

    def require(self, allowed, action: str) -> None:
        with self.lock:
            if self._state not in allowed:
                raise StateConflict(f"{action} not allowed in state {self._state!r}")

    @contextmanager
    def operation(self, action: str, busy: str = ""):
        """Mark the session busy for the duration of `action`; on exception fall to ERROR.
        Refuses a second concurrent operation so two commands cannot fight over the page."""
        self.require(_OPEN, action)
        self.command_seq += 1
        if busy:
            self.set(busy, action)
        try:
            yield self
        except Exception as e:
            self.set(ERROR, f"{action}: {type(e).__name__}: {e}")
            raise
