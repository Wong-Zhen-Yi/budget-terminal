# Financial research defaults

For stock-market, company, earnings, valuation, portfolio, market-news, or macroeconomic research, use the `analyze-stocks-macro` skill.

Treat current news skeptically. For every material news claim:

- verify the original source and exact dates;
- separate confirmed fact from interpretation and forecast;
- compare the development with prior expectations;
- estimate the economic channel, magnitude, and time horizon;
- test at least one credible alternative explanation and seek disconfirming evidence;
- state confidence and unresolved evidence gaps.

Prefer primary sources and current official data. Never infer a conclusion from a headline alone, confuse repeated coverage with independent confirmation, or present an inference as reported fact.

# Repository Guidelines

## Project Structure & Module Organization
`budget_terminal.py` is the top-level launcher. The live PySide6 application now lives under `budget_terminal_app/`, with `main.py` creating the Qt app and `app.py` defining `BudgetTerminalApp`.

Keep changes close to the subsystem they affect:
- `budget_terminal_app/mixins/`: window, page, and feature behavior
- `budget_terminal_app/workers/`: background data fetchers and signal-driven tasks
- `budget_terminal_app/services/`: presentation-independent data access and analytics
- `budget_terminal_app/data_service/`: shared fetch coordinator plus the in-process and HTTP clients
- `budget_terminal_app/widgets/`: custom charts and visual widgets
- `budget_terminal_app/themes/`: default theme tokens and stylesheet helpers
- `budget_terminal_app/paper_trading/`: sqlite-backed simulated-trading engine and store
- `budget_terminal_app/cache.py`, `persistence.py`, `paths.py`, `constants.py`, `dependencies.py`: shared infrastructure

`CLAUDE.md` is the reference for how the mixin composition, the two page-numbering schemes, and the page registries fit together. Read it before adding or moving a page.

Scripts named `test_*.py` are focused smoke tests. Reusable manual probes live under `scripts/diagnostics/`. Packaging files live in `packaging/`. Build and release artifacts live in `build/`, `dist/`, and `release/` and should be treated as generated output unless a task explicitly targets packaging.

## Build, Test, and Development Commands
Create a virtual environment with `python -m venv .venv`, then install dependencies with `.\.venv\Scripts\python.exe -m pip install --upgrade --upgrade-strategy eager -r requirements.txt -r requirements-dev.txt`. The dev requirements carry Ruff, PyInstaller, and `pip-audit`, all of which CI runs.

Common commands:
- `python budget_terminal.py`: launch the desktop app
- `python -m compileall budget_terminal.py budget_terminal_app`: quick syntax check for the launcher and package
- `.\.venv\Scripts\python.exe -m ruff check budget_terminal.py budget_terminal_app scripts`: static quality check
- `.\.venv\Scripts\python.exe scripts\test_data_service_transport.py`: deterministic data-layer smoke test
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
There is no formal `pytest` suite in this checkout. Every `scripts/test_*.py` is a standalone module with its own `__main__` block, run directly rather than collected by a test runner. Do not add pytest invocations.

`.github/workflows/python-ci.yml` is the authoritative list of checks that gate a merge — the privacy scan, `pip-audit`, Ruff, `compileall`, and two batches of smoke tests. Mirror the subset that matches what you touched before pushing.

Typical verification:
- launch the app for UI, startup, theme, or persistence changes
- run `python -m compileall budget_terminal.py budget_terminal_app` for Python edits
- run focused `scripts/` test or debug scripts for data-fetching changes
- confirm modified workflows or packaging scripts execute without obvious errors when relevant

Anything that constructs Qt widgets needs an offscreen platform when run headless, the same way CI does it:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'; .\.venv\Scripts\python.exe scripts\test_refresh_responsiveness.py
```

`scripts/test_public_repo_privacy.py` runs first in CI and rejects absolute user home directories, email addresses, and credential-shaped strings in any git-tracked file. Keep paths repo-relative in code, docs, and tests.

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
