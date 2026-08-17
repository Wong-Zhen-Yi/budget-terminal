# Budget Terminal

Budget Terminal is a Windows-focused PyQt6 desktop app for tracking portfolio data, market context, options chains, news, ETF analysis, charts, and related research workflows. The top-level `budget_terminal.py` launcher remains the stable entry point, while the live application code is organized under `budget_terminal_app/`.

## Features

- Portfolio dashboard, net worth tracking, holdings metrics, and sector views
- Options-chain fetching and table rendering
- News hub with deterministic headline briefings, politics, calendar, pre-market, and YouTube helpers
- Fundamentals and valuation
- Earnings matrix, ETF analysis, SPY/ETF heatmaps, random recommendations, and chart pages
- Default theme support through reusable theme tokens and shared styling helpers
- In-process market-data coordination by default, with HTTP compatibility mode and direct-worker fallback

## Project Layout

- `budget_terminal.py`: top-level launcher; auto-runs through `.venv` when available
- `budget_terminal_app/main.py`: Qt application setup, startup loading screen, app icon, and embedded data-service startup
- `budget_terminal_app/app.py`: composed `BudgetTerminalApp` main-window class
- `budget_terminal_app/mixins/`: page, window, and feature behavior
- `budget_terminal_app/workers/`: background data fetchers and signal-driven tasks
- `budget_terminal_app/widgets/`: custom charts, pie/bar charts, and heatmap widgets
- `budget_terminal_app/themes/`: default theme tokens and stylesheet helpers
- `budget_terminal_app/data_service/`: shared coordinator plus in-process and compatible FastAPI/HTTP clients
- `budget_terminal_app/services/`: reusable market-data, analytics, and presentation-independent calculations
- `budget_terminal_app/cache.py`, `persistence.py`, `paths.py`, `constants.py`, `dependencies.py`: shared infrastructure

## Setup

Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip==26.1.2 setuptools==83.0.0
.\.venv\Scripts\python.exe -m pip install --upgrade --upgrade-strategy eager -r requirements.txt
```

Run the app:

```powershell
python budget_terminal.py
```

When `.venv` exists, the launcher re-executes itself with `.\.venv\Scripts\python.exe` unless `BUDGET_TERMINAL_SKIP_LOCAL_VENV=1` is set.

## Open Multiple Windows

Run the launch command again whenever you want another Budget Terminal window:

```powershell
python budget_terminal.py
```

Each launch starts an independent app process. The windows share the same saved portfolios, settings, caches, and paper-trading database. Avoid changing the same saved setting in two windows at exactly the same time; for JSON-backed settings, the most recent save wins.

## Runtime Flow

`budget_terminal_app/main.py` creates the Qt application, applies the Fusion style, configures pyqtgraph, shows the startup loading screen, imports `BudgetTerminalApp`, and prepares the main window before first show. After the first usable view is visible, the shared data coordinator starts in-process. If it is unavailable, the app logs the issue and continues with direct worker behavior.

Set `BUDGET_TERMINAL_DATA_TRANSPORT=http` to run the compatible private FastAPI/Uvicorn localhost transport for diagnostics. The default `inprocess` transport uses the same coordinator contract without JSON serialization or a loopback socket.

Long-running fetches live in worker objects and report results back through Qt signals so the UI stays responsive. Writable user data is resolved through `budget_terminal_app/paths.py` instead of being stored beside the packaged executable.

## News Briefing

The News Hub briefing is generated inside the app and does not use an LLM.

- Briefings are generated from headline text, ticker, source, time, and category
- Full briefings auto-refresh when news updates load
- Clicking a headline row produces a single-item summary
- `Generate Briefing` reruns the deterministic digest manually
- Output includes overall tone, theme counts, portfolio names, macro drivers, latest headlines, notable headlines, and headline-only cautions

## User Data Safety

Do not commit personal portfolio data, API keys, generated cache databases, or machine-specific runtime files. Packaged builds store writable app data under `%LOCALAPPDATA%\BudgetTerminal`, with user-facing document data under `Documents\Budget Terminal User Data` when needed.
