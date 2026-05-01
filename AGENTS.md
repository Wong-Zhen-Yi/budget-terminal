# Repository Guidelines

## Project Structure & Module Organization
`budget_terminal.py` is the top-level launcher. The live PyQt6 application now lives under `budget_terminal_app/`, with `main.py` creating the Qt app and `app.py` defining `BudgetTerminalApp`.

Keep changes close to the subsystem they affect:
- `budget_terminal_app/mixins/`: window, page, and feature behavior
- `budget_terminal_app/workers/`: background data fetchers and signal-driven tasks
- `budget_terminal_app/widgets/`: custom charts and visual widgets
- `budget_terminal_app/themes/`: theme tokens and theme implementations
- `budget_terminal_app/cache.py`, `persistence.py`, `paths.py`, `constants.py`, `dependencies.py`: shared infrastructure

Scripts under `scripts/` such as `test_options_fetch.py`, `debug_yf.py`, `inspect_cache.py`, and related helpers are ad hoc diagnostics and smoke tests. Packaging files live in `packaging/`. Build and release artifacts live in `build/`, `dist/`, and `release/` and should be treated as generated output unless a task explicitly targets packaging.

## Build, Test, and Development Commands
Create a virtual environment with `python -m venv .venv`, then install dependencies with `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

Common commands:
- `python budget_terminal.py`: launch the desktop app
- `python -m compileall budget_terminal.py budget_terminal_app`: quick syntax check for the launcher and package
- `python scripts\test_options_fetch.py`: smoke-test Yahoo Finance options fetching
- `.\packaging\build_exe.bat`: build the Windows executable package

If a change affects a specific helper script, run that script directly as part of verification.

## Coding Style & Naming Conventions
Follow the existing Python style already used throughout the package:
- 4-space indentation
- `snake_case` for functions, methods, and variables
- `PascalCase` for classes
- `UPPER_CASE` for module-level constants

Prefer small, targeted edits over sweeping rewrites. Add new helpers in the module that owns the behavior, or in the nearest shared support module when the logic is reused across features. Preserve the current import style and file layout unless the task specifically requires refactoring.

## Testing Guidelines
There is no formal `pytest` suite in this checkout, so validation is primarily smoke-test based. Run the checks that match the code you touched.

Typical verification:
- launch the app for UI, startup, theme, or persistence changes
- run `python -m compileall budget_terminal.py budget_terminal_app` for Python edits
- run focused `scripts/` test or debug scripts for data-fetching changes
- confirm modified workflows or packaging scripts execute without obvious errors when relevant

Name any new ad hoc verification script `test_<feature>.py` and keep it under `scripts/` unless there is a clear reason to colocate it elsewhere.

## Commit & Pull Request Guidelines
Git history may not be available in every workspace snapshot, so use short, imperative commit titles such as `Fix options refresh state` or `Update theme token defaults`.

Pull requests should include:
- a brief user-facing summary
- manual verification steps
- screenshots for UI changes
- packaging notes when the executable build flow changes

## Configuration & Data Safety
Do not commit personal portfolio data, API keys, generated cache databases, or machine-specific runtime files. Be careful around JSON and cache files in the repository root and any app data mirrored during local testing.

For packaged builds, user-writable data belongs under `%LOCALAPPDATA%\BudgetTerminal`. Keep new local-only outputs in ignored locations such as `screenshots/` or other clearly temporary directories.
