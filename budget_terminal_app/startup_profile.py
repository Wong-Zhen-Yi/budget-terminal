from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Iterator

_FALSEY_ENV_VALUES = {'', '0', 'false', 'no', 'off'}


class StartupProfiler:
    """Collect lightweight startup timings and emit concise logs."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger if logger is not None else logging.getLogger(__name__)
        raw_flag = os.getenv('BUDGET_TERMINAL_STARTUP_PROFILE', '')
        self.detailed = str(raw_flag or '').strip().lower() not in _FALSEY_ENV_VALUES
        self.started_at = time.perf_counter()
        self._records: list[dict[str, float | str]] = []
        self._summary_logged = False

    def _record(self, kind: str, name: str, seconds: float) -> float:
        entry = {'kind': kind, 'name': str(name), 'seconds': float(seconds)}
        self._records.append(entry)
        if self.detailed:
            if kind == 'stamp':
                self.logger.info('Startup %s at %.3fs', name, seconds)
            else:
                self.logger.info('Startup step %s finished in %.3fs', name, seconds)
        return float(seconds)

    def stamp(self, name: str) -> float:
        """Record elapsed time from process startup to one milestone."""
        return self._record('stamp', name, time.perf_counter() - self.started_at)

    def elapsed(self) -> float:
        """Return current elapsed startup time in seconds."""
        return float(time.perf_counter() - self.started_at)

    def add_duration(self, name: str, seconds: float) -> float:
        """Record one named duration."""
        return self._record('duration', name, seconds)

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        """Measure the duration of a startup sub-step."""
        started = time.perf_counter()
        try:
            yield
        finally:
            self.add_duration(name, time.perf_counter() - started)

    def records(self) -> list[dict[str, float | str]]:
        """Return a copy of the captured timing records."""
        return [dict(record) for record in self._records]

    def latest(self, name: str) -> float | None:
        """Return the latest recorded value for a named startup record."""
        return self._find_latest(name)

    def snapshot(self) -> dict[str, float | list[dict[str, float | str]]]:
        """Return a serializable snapshot of current startup timings."""
        return {
            'elapsed_seconds': self.elapsed(),
            'records': self.records(),
        }

    @staticmethod
    def format_seconds(value: float | int | None) -> str:
        """Return a compact human-readable startup timing value."""
        if value is None:
            return '-'
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return '-'
        if seconds < 0:
            return '-'
        if seconds < 1:
            return f'{seconds * 1000:.0f} ms'
        return f'{seconds:.2f} s'

    def _find_latest(self, name: str) -> float | None:
        for record in reversed(self._records):
            if record.get('name') == name:
                return float(record.get('seconds', 0.0) or 0.0)
        return None

    def log_summary(self) -> None:
        """Emit one concise startup summary at info level."""
        if self._summary_logged:
            return
        self._summary_logged = True
        summary_parts = []
        for name in ('import_app', 'window_init', 'window_shown'):
            value = self._find_latest(name)
            if value is not None:
                summary_parts.append(f'{name}={value:.3f}s')
        if not summary_parts and self._records:
            last = self._records[-1]
            summary_parts.append(f'{str(last.get("name", "startup"))}={float(last.get("seconds", 0.0) or 0.0):.3f}s')
        if summary_parts:
            self.logger.info('Startup summary | %s', ' | '.join(summary_parts))
