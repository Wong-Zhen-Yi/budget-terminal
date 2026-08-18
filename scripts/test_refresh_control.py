from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from budget_terminal_app.services.refresh_control import RefreshCoordinator


def test_single_flight_and_latest_pending() -> None:
    coordinator = RefreshCoordinator()

    first, should_start = coordinator.request("portfolio:positions", ("main", "AAA"))
    assert should_start
    assert first.page == "portfolio:positions"
    assert first.input_signature == ("main", "AAA")
    duplicate, should_start = coordinator.request("portfolio:positions", ("main", "AAA"))
    assert duplicate == first and not should_start
    assert coordinator.is_active(first)
    assert coordinator.is_current(first)

    second, should_start = coordinator.request("portfolio:positions", ("main", "BBB"))
    assert not should_start
    assert second.generation == first.generation + 1
    assert coordinator.is_active(first)
    assert not coordinator.is_current(first)
    assert coordinator.is_current(second)

    second_duplicate, should_start = coordinator.request("portfolio:positions", ("main", "BBB"))
    assert second_duplicate == second and not should_start

    third, should_start = coordinator.request("portfolio:positions", ("main", "CCC"))
    assert not should_start
    assert third.generation == second.generation + 1
    assert coordinator.pending_token("portfolio:positions") == third
    assert not coordinator.is_current(second)
    assert coordinator.is_current(third)

    promoted = coordinator.complete(first)
    assert promoted == third
    assert coordinator.is_active(third)
    assert coordinator.complete(first) is None
    assert coordinator.complete(third) is None
    assert coordinator.active_token("portfolio:positions") is None


def test_latest_request_can_return_to_active_signature() -> None:
    coordinator = RefreshCoordinator()
    active, _ = coordinator.begin("calendar", 2026)
    pending, should_start = coordinator.begin("calendar", 2027)
    assert not should_start and pending != active

    active_again, should_start = coordinator.begin("calendar", 2026)
    assert active_again == active and not should_start
    assert coordinator.pending_token("calendar") is None
    assert coordinator.current(active)
    assert coordinator.finish(active) is None


def test_cancel_clear_and_validation() -> None:
    coordinator = RefreshCoordinator()
    one, _ = coordinator.request("one", (1,))
    two, _ = coordinator.request("one", (2,))
    three, _ = coordinator.request("two", (3,))

    assert coordinator.cancel("one") == (one, two)
    assert not coordinator.is_current(one)
    assert coordinator.clear() == (three,)
    assert coordinator.clear() == ()

    try:
        coordinator.request("bad", ["mutable"])
    except TypeError as exc:
        assert "signature" in str(exc)
    else:
        raise AssertionError("unhashable signatures must be rejected")


if __name__ == "__main__":
    test_single_flight_and_latest_pending()
    test_latest_request_can_return_to_active_signature()
    test_cancel_clear_and_validation()
    print("Refresh coordinator tests passed.")
