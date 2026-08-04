from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.mixins.window_lifecycle import REFRESH_ROUTE_ARCHITECTURE, REFRESH_ROUTE_CLASSIFICATION
from budget_terminal_app.mixins.window_lifecycle import WindowLifecycleMixin
from budget_terminal_app.mixins.window_setup import WindowSetupMixin


class _Stack:
    def __init__(self) -> None:
        self.index = 0

    def currentIndex(self) -> int:
        return self.index


class _RefreshRouteProbe(WindowLifecycleMixin):
    def __init__(self) -> None:
        self.stacked_widget = _Stack()
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        if name.startswith('_p') or name in {
            'refresh_data',
            'load_valuation_data',
            'analyze_stock_p2',
            'set_status_text',
        }:
            def _record(*_args, **_kwargs):
                self.calls.append(name)
                return None

            return _record
        raise AttributeError(name)


def test_every_registered_page_has_a_refresh_architecture() -> None:
    page_indexes = set(WindowSetupMixin._PAGE_LABELS)
    classified_indexes = set(REFRESH_ROUTE_ARCHITECTURE)
    assert classified_indexes == page_indexes, (
        f"refresh inventory mismatch: missing={sorted(page_indexes - classified_indexes)}, "
        f"unknown={sorted(classified_indexes - page_indexes)}"
    )
    allowed = {
        "local-only",
        "background-coordinated",
        "background-single-flight",
        "background-active-subtab",
    }
    assert set(REFRESH_ROUTE_ARCHITECTURE.values()) <= allowed
    assert set(REFRESH_ROUTE_CLASSIFICATION) == page_indexes
    assert set(REFRESH_ROUTE_CLASSIFICATION.values()) <= {"local-only", "background-safe", "migrated"}
    assert REFRESH_ROUTE_ARCHITECTURE[1] == "background-coordinated"
    assert REFRESH_ROUTE_ARCHITECTURE[3] == "background-coordinated"
    assert REFRESH_ROUTE_ARCHITECTURE[9] == "background-active-subtab"
    assert REFRESH_ROUTE_ARCHITECTURE[11] == "background-active-subtab"
    assert REFRESH_ROUTE_ARCHITECTURE[31] == "background-active-subtab"
    newly_migrated = {13, 14, 15, 16, 18, 20, 24, 25, 28, 33}
    assert {index for index in newly_migrated if REFRESH_ROUTE_CLASSIFICATION[index] != "migrated"} == set()


def test_every_classified_route_dispatches_an_action() -> None:
    probe = _RefreshRouteProbe()
    for page_index in sorted(REFRESH_ROUTE_ARCHITECTURE):
        probe.stacked_widget.index = page_index
        probe.calls.clear()
        probe._refresh_current_page()
        assert probe.calls, f"page index {page_index} is classified but has no refresh dispatch"


if __name__ == "__main__":
    test_every_registered_page_has_a_refresh_architecture()
    test_every_classified_route_dispatches_an_action()
    print("Refresh route inventory tests passed.")
