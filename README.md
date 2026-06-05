# Budget Terminal v0.904

Budget Terminal is a Windows-focused PyQt6 desktop app for tracking portfolio data, market context, options chains, news, ETF analysis, charts, and related research workflows. The top-level `budget_terminal.py` launcher remains the stable entry point, while the live application code is organized under `budget_terminal_app/`.

## Features

- Portfolio dashboard, net worth tracking, holdings metrics, and sector views
- Options-chain fetching, table rendering, and related Yahoo Finance smoke tests
- News hub with deterministic headline briefings, politics, calendar, pre-market, and YouTube helpers
- Fundamentals, earnings matrix, ETF analysis, SPY/ETF heatmaps, random recommendations, and chart pages
- Default theme support through reusable theme tokens and shared styling helpers
- Embedded local data service for background market-data coordination, with direct-worker fallback

## Project Layout

- `budget_terminal.py`: top-level launcher; auto-runs through `.venv` when available
- `budget_terminal_app/main.py`: Qt application setup, startup loading screen, app icon, and embedded data-service startup
- `budget_terminal_app/app.py`: composed `BudgetTerminalApp` main-window class
- `budget_terminal_app/mixins/`: page, window, and feature behavior
- `budget_terminal_app/workers/`: background data fetchers and signal-driven tasks
- `budget_terminal_app/widgets/`: custom charts, pie/bar charts, and heatmap widgets
- `budget_terminal_app/themes/`: default theme tokens and stylesheet helpers
- `budget_terminal_app/data_service/`: embedded FastAPI/HTTP data service runtime, client, coordinator, and serialization helpers
- `budget_terminal_app/cache.py`, `persistence.py`, `paths.py`, `constants.py`, `dependencies.py`: shared infrastructure
- `scripts/`: ad hoc diagnostics and smoke tests
- `packaging/`: PyInstaller specs and build scripts
- `build/`, `dist/`, `release/`: generated build outputs

## Setup

Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run the app:

```powershell
python budget_terminal.py
```

When `.venv` exists, the launcher re-executes itself with `.\.venv\Scripts\python.exe` unless `BUDGET_TERMINAL_SKIP_LOCAL_VENV=1` is set.

## Development

Use the checks that match the code you touched. Common commands:

```powershell
python -m compileall budget_terminal.py budget_terminal_app
python scripts\test_options_fetch.py
python scripts\test_startup_profile.py
```

Helpful diagnostics include:

- `python scripts\debug_yf.py`
- `python scripts\debug_yf_extended.py`
- `python scripts\inspect_cache.py`
- `python scripts\check_news.py`

There is no formal `pytest` suite in this checkout, so UI and data-fetching changes should be verified with focused smoke tests and, when relevant, a manual app launch.

## Runtime Flow

`budget_terminal_app/main.py` creates the Qt application, applies the Fusion style, configures pyqtgraph, shows the startup loading screen, imports `BudgetTerminalApp`, and prepares the main window before first show. After the first usable view is visible, the embedded data service starts in the background. If it is unavailable, the app logs the issue and continues with direct worker behavior.

Long-running fetches live in worker objects and report results back through Qt signals so the UI stays responsive. Writable user data is resolved through `budget_terminal_app/paths.py` instead of being stored beside the packaged executable.

## News Briefing

The News Hub briefing is generated inside the app and does not use an LLM.

- Briefings are generated from headline text, ticker, source, time, and category
- Full briefings auto-refresh when news updates load
- Clicking a headline row produces a single-item summary
- `Generate Briefing` reruns the deterministic digest manually
- Output includes overall tone, theme counts, portfolio names, macro drivers, latest headlines, notable headlines, and headline-only cautions

## Windows Executable Build

This is a PyQt6 desktop GUI app, so the standard packaging target is a windowed PyInstaller build from `budget_terminal.py`.

Install build prerequisites:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
```

Build the executable package:

```powershell
.\packaging\build_exe.bat
```

The build script:

- activates `.venv`
- installs `requirements.txt` plus `pyinstaller`
- removes old `build/` output and only the current-version `dist/` target
- builds from `packaging\budget_terminal.spec`
- creates `release\BudgetTerminal-v*-windows.zip`

See `packaging\PACKAGING.md` for the one-dir build flow, release outputs, and troubleshooting notes.

## User Data Safety

Do not commit personal portfolio data, API keys, generated cache databases, or machine-specific runtime files. Packaged builds store writable app data under `%LOCALAPPDATA%\BudgetTerminal`, with user-facing document data under `Documents\Budget Terminal User Data` when needed.
