# Repository Guidelines

## Project Structure & Module Organization
`budget_terminal.py` is the main application and contains the PyQt6 UI, data workers, charting, caching, and persistence logic. Supporting scripts such as `check_news.py`, `debug_yf.py`, `inspect_cache.py`, and `test_options_fetch.py` are root-level utilities for targeted debugging. Runtime data files like `portfolio.json` and `portfolio_tracker.json` also live at the repository root. GitHub automation is under `.github/workflows/` and `.github/commands/`.

## Build, Test, and Development Commands
Create a virtual environment and install dependencies with `python -m venv .venv` and `.\.venv\Scripts\pip install -r requirements.txt`. Run the desktop app with `python budget_terminal.py`. Use `python test_options_fetch.py` to sanity-check Yahoo Finance options access, and `python -m compileall budget_terminal.py` for a quick syntax check before submitting changes.

## Coding Style & Naming Conventions
Follow the existing Python style in `budget_terminal.py`: 4-space indentation, `snake_case` for functions and variables, `PascalCase` for classes, and uppercase names for module-level constants like `PORTFOLIO_FILE`. Keep new helpers close to the feature they support, and prefer small, targeted edits over broad reformatting. There is no configured formatter in this checkout, so preserve the current layout and import style.

## Testing Guidelines
This repository does not include a formal `pytest` suite yet. Treat focused scripts as smoke tests and run the ones relevant to your change. For UI or persistence updates, verify that the app launches cleanly, data files still load, and any edited workflow or utility script runs without tracebacks. Name new ad hoc test scripts `test_<feature>.py` for consistency with the existing root-level pattern.

## Commit & Pull Request Guidelines
Git history is not available in this workspace snapshot, so no repository-specific commit convention can be confirmed here. Use short, imperative commit subjects such as `Fix tracker totals rounding` or `Add cache guard for options fetch`. Pull requests should describe the user-visible change, list manual verification steps, and include screenshots when the UI changes.

## Configuration & Data Safety
Do not commit personal portfolio data, API credentials, or generated cache files. Keep any new local-only outputs alongside the existing JSON/cache files or in a dedicated ignored directory such as `screenshots/`.
