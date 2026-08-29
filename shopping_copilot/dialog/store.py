"""Thread-safe session state registry and lifecycle manager."""

from __future__ import annotations

import threading
from typing import Mapping

from shopping_copilot.dialog.models import (
    ActiveState,
    CustomerProfile,
    DialogueContext,
    SessionState,
    TurnRecord,
)
from shopping_copilot.understanding.models import Attribute


class SessionStore:
    """Thread-safe session store managing isolated session states across turns."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, SessionState] = {}

    def reset(self, session_id: str, user_profile: dict | CustomerProfile | None) -> SessionState:
        """Initialize or reset session state with given user profile."""
        if isinstance(user_profile, CustomerProfile):
            profile = user_profile
        else:
            profile = CustomerProfile.from_dict(user_profile)

        initial_state = SessionState(
            session_id=session_id,
            user_profile=profile,
            active_state=ActiveState(turn=0),
            turn_history=(),
            last_ask_attribute=None,
            last_recommendations=(),
        )

        with self._lock:
            self._sessions[session_id] = initial_state
            return initial_state

    def get_session(self, session_id: str) -> SessionState:
        """Retrieve existing session state or raise KeyError."""
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(f"Session '{session_id}' not found. reset() must be called first.")
            return self._sessions[session_id]

    def has_session(self, session_id: str) -> bool:
        """Check if session is currently registered."""
        with self._lock:
            return session_id in self._sessions

    def get_dialogue_context(self, session_id: str, turn: int) -> DialogueContext:
        """Construct DialogueContext for the current turn."""
        with self._lock:
            session = self.get_session(session_id)
            return DialogueContext(
                active_state=session.active_state,
                last_ask_attribute=session.last_ask_attribute,
                last_recommendations=session.last_recommendations,
                turn=turn,
            )

    def update_active_state(self, session_id: str, active_state: ActiveState) -> None:
        """Update active state for a session."""
        with self._lock:
            session = self.get_session(session_id)
            self._sessions[session_id] = SessionState(
                session_id=session.session_id,
                user_profile=session.user_profile,
                active_state=active_state,
                turn_history=session.turn_history,
                last_ask_attribute=session.last_ask_attribute,
                last_recommendations=session.last_recommendations,
            )

    def record_turn(
        self,
        session_id: str,
        turn_record: TurnRecord,
        ask_attribute: Attribute | None = None,
        recommendations: tuple[str, ...] = (),
    ) -> None:
        """Append turn record and update last ask/recommendations."""
        with self._lock:
            session = self.get_session(session_id)
            updated_history = session.turn_history + (turn_record,)
            self._sessions[session_id] = SessionState(
                session_id=session.session_id,
                user_profile=session.user_profile,
                active_state=session.active_state,
                turn_history=updated_history,
                last_ask_attribute=ask_attribute,
                last_recommendations=recommendations,
            )

    def clear(self) -> None:
        """Clear all active sessions."""
        with self._lock:
            self._sessions.clear()

