"""Launch the Budget Terminal desktop application."""

from __future__ import annotations

try:
    from budget_terminal_app.main import main
except ModuleNotFoundError as exc:
    missing_module = exc.name or "a required package"
    raise SystemExit(
        "Missing dependency: "
        f"{missing_module}\n"
        "Install project requirements with:\n"
        "python -m pip install -r requirements.txt"
    ) from exc

if __name__ == "__main__":
    raise SystemExit(main())