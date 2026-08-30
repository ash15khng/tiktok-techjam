"""Isolated in-process session lifecycle."""

from __future__ import annotations

from threading import RLock

from submission.src.dialog.models import SessionState


class SessionStore:
    """Map from session ID to Session state. Stored in memory."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = RLock()

    def reset(self, session_id: str, customer_profile: dict) -> SessionState:
        """Replace any prior state and return the new empty session."""

        with self._lock:
            state = SessionState(str(session_id), dict(customer_profile))
            self._sessions[str(session_id)] = state
            return state

    def get(self, session_id: str) -> SessionState:
        """Return existing state or fail clearly when ``reset`` was omitted."""

        with self._lock:
            if session_id not in self._sessions:
                raise RuntimeError("reset must be called before respond")
            return self._sessions[session_id]
