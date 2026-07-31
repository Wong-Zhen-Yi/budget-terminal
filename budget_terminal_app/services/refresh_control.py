"""Thread-safe single-flight coordination for page refresh requests.

The coordinator deliberately has no Qt dependency.  UI code can request work on
the GUI thread and complete it from a queued worker callback without coupling the
request lifecycle to a particular worker implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Hashable


@dataclass(frozen=True, slots=True)
class RefreshToken:
    """Immutable identity for one logical refresh request."""

    page: Hashable
    generation: int
    input_signature: Hashable

    @property
    def key(self) -> Hashable:
        """Backward-compatible coordinator key for the page or subpage."""
        return self.page

    @property
    def signature(self) -> Hashable:
        """Backward-compatible alias for the captured input signature."""
        return self.input_signature


@dataclass(slots=True)
class _RefreshState:
    active: RefreshToken
    pending: RefreshToken | None = None


class RefreshCoordinator:
    """Coordinate one active refresh and at most one pending rerun per key.

    ``request`` returns ``(token, should_start)``.  A duplicate of either the
    active or pending signature reuses that token.  A different signature while
    work is active replaces the pending request, so only the latest state is run.

    Call ``complete`` for every launched token, including failed work.  It
    returns the pending token when a rerun should now start.  Callers may cache a
    completed result before checking ``is_current``; an active token stops being
    current as soon as a newer signature is pending.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._states: dict[Hashable, _RefreshState] = {}
        self._generations: dict[Hashable, int] = {}

    def request(self, key: Hashable, signature: Hashable) -> tuple[RefreshToken, bool]:
        """Register a request and return its token plus whether to start it now."""
        self._validate_hashable("key", key)
        self._validate_hashable("signature", signature)
        with self._lock:
            state = self._states.get(key)
            if state is None:
                token = self._new_token(key, signature)
                self._states[key] = _RefreshState(active=token)
                return token, True

            if state.pending is not None and state.pending.signature == signature:
                return state.pending, False

            if state.active.signature == signature:
                # The latest desired state matches work already in flight.  Any
                # queued request for an intermediate state is no longer needed.
                state.pending = None
                return state.active, False

            token = self._new_token(key, signature)
            state.pending = token
            return token, False

    def begin(self, key: Hashable, signature: Hashable) -> tuple[RefreshToken, bool]:
        """Alias for :meth:`request`, convenient at refresh entry points."""
        return self.request(key, signature)

    def complete(self, token: RefreshToken) -> RefreshToken | None:
        """Finish an active token and return the latest pending token to launch."""
        with self._lock:
            state = self._states.get(token.key)
            if state is None or state.active != token:
                return None

            next_token = state.pending
            if next_token is None:
                del self._states[token.key]
                return None

            state.active = next_token
            state.pending = None
            return next_token

    def finish(self, token: RefreshToken) -> RefreshToken | None:
        """Alias for :meth:`complete`; failures use the same lifecycle cleanup."""
        return self.complete(token)

    def is_current(self, token: RefreshToken) -> bool:
        """Return whether *token* represents the latest requested state."""
        with self._lock:
            state = self._states.get(token.key)
            if state is None:
                return False
            latest = state.pending if state.pending is not None else state.active
            return latest == token

    def current(self, token: RefreshToken) -> bool:
        """Alias for :meth:`is_current`."""
        return self.is_current(token)

    def is_active(self, token: RefreshToken) -> bool:
        """Return whether *token* is the request currently doing work."""
        with self._lock:
            state = self._states.get(token.key)
            return state is not None and state.active == token

    def active_token(self, key: Hashable) -> RefreshToken | None:
        """Return the active token for *key*, if any."""
        with self._lock:
            state = self._states.get(key)
            return state.active if state is not None else None

    def pending_token(self, key: Hashable) -> RefreshToken | None:
        """Return the newest queued token for *key*, if any."""
        with self._lock:
            state = self._states.get(key)
            return state.pending if state is not None else None

    def cancel(self, key: Hashable) -> tuple[RefreshToken, ...]:
        """Forget coordinated state for *key* and return the removed tokens.

        This does not attempt to stop an external worker.  A later completion
        from a removed token is safely ignored.
        """
        with self._lock:
            state = self._states.pop(key, None)
            if state is None:
                return ()
            if state.pending is None:
                return (state.active,)
            return state.active, state.pending

    def clear(self) -> tuple[RefreshToken, ...]:
        """Forget all active and pending state, typically during shutdown."""
        with self._lock:
            removed: list[RefreshToken] = []
            for state in self._states.values():
                removed.append(state.active)
                if state.pending is not None:
                    removed.append(state.pending)
            self._states.clear()
            return tuple(removed)

    def _new_token(self, key: Hashable, signature: Hashable) -> RefreshToken:
        generation = self._generations.get(key, 0) + 1
        self._generations[key] = generation
        return RefreshToken(page=key, generation=generation, input_signature=signature)

    @staticmethod
    def _validate_hashable(name: str, value: Hashable) -> None:
        try:
            hash(value)
        except TypeError as exc:
            raise TypeError(f"refresh {name} must be hashable") from exc
