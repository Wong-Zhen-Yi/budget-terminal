# Budget Terminal

Budget Terminal is a Windows-focused PySide6 desktop app for portfolio tracking, market context,
options chains, signals, quant screens, news, ETF analysis, and related research workflows. The
top-level `budget_terminal.py` launcher is the stable entry point; the live application code lives
under `budget_terminal_app/`.

Nothing in the app is investment advice. Every scoring, ranking, and projection surface is decision
support only.

## Setup

Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
```

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip==26.1.2 setuptools==83.0.0
```

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade --upgrade-strategy eager -r requirements.txt -r requirements-dev.txt
```

Run the app:

```powershell
python budget_terminal.py
```

When `.venv` exists, the launcher re-executes itself with `.\.venv\Scripts\python.exe` unless
`BUDGET_TERMINAL_SKIP_LOCAL_VENV=1` is set. `requirements-dev.txt` is only needed for linting and
packaging; the app itself runs on `requirements.txt` alone.

If you are not a developer, `LAUNCH_APP.md` walks through the same steps in more detail.

## Pages

The app ships 32 pages. Only the Dashboard and the Global map are built during startup — every other
page is constructed the first time you open it, so first paint stays fast. Pages can be reordered or hidden from
Settings -> Workspace; the shipped tab order is `DEFAULT_NAVIGATION_PAGE_ORDER` in `persistence.py`.
The tables below group the same 32 pages by what they are for rather than by tab position. Personal
Finance is obscured by default (`DEFAULT_PRIVACY_SETTINGS`).

### Overview

| Page | What it does |
| --- | --- |
| Dashboard | Watchlist entry plus a portfolio table (price, change, weight, gain) and a compact live news feed. Built eagerly during startup. |
| Global | World market-index map at a selectable interval. Also built during startup. |
| Cards | Equal-weight, custom-weight, and live portfolio baskets rendered as strategy cards with performance. |

### Money you own

| Page | What it does |
| --- | --- |
| Portfolio | Up to five saved portfolios plus a Combined view: positions, totals, margin debt, and lookback metrics. |
| Personal Finance | Cash, debt, recurring bills, and a savings goal, totalled in SGD or USD with a live FX rate. Obscured by default. |
| Projections | A chart workstation paired with all-expiration top-volume options for the same symbol. |

### Market context

| Page | What it does |
| --- | --- |
| Pre-Market | Pre-market movers and session summary. |
| Up/Down | Counts of advancing versus declining names across your portfolio or a custom symbol list, per interval. |
| Trading Volumes | Most-traded names, with an export-for-LLM action. |
| Price | Screener of the top names by market cap, as a sortable table and a price-versus-market-cap scatter. |
| Heatmap | Holdings heatmap for SPY and other ETFs. |
| Calendar | Economic calendar and earnings, on separate tabs. |
| Economic | Headline US macro releases from FRED: inflation, labour, growth, and the full treasury curve. |

### Research

| Page | What it does |
| --- | --- |
| Stocks | Single-symbol overview with chart, statistics, and key figures. |
| Fundamentals | Statements and metrics for one company, with a second company in a compare column. |
| Valuation | Scenario-driven valuation with assumptions, peers, risk, trends, notes, and sources tabs. |
| Charts | Chart workstation: intervals, ranges, drawings, comparison series, and optional polling. |
| Options | Options chain by expiry, top-volume tabs by bucket, and a strike view. |
| ETF | ETF analyser with holdings, AUM, and premium/arbitrage detail. |
| Crypto | Crypto market dashboard with a saved watchlist. |
| IPO | Completed IPOs and upcoming US IPOs through year-end. Dates are estimates. |
| Institutions | Latest DATAROMA superinvestor activity by quarter. |

### Signals and quant

| Page | What it does |
| --- | --- |
| Signals | Sources liquid US leaders on demand, then scores Daily to Hourly to 5-minute to 1-minute analysis out of 100, graded and measured in ATR. |
| Quant | Sources its own liquid US universe, ranks it on cross-sectional factors, and hunts mean-reverting pairs. |
| Backtest | Runs a weighted symbol basket against a comparison symbol over a chosen interval and range. |
| Roll | Rolls a random liquid US stock and shows its metrics alongside a breakdown of why it surfaced. |

### News and media

| Page | What it does |
| --- | --- |
| News | Magazine-style news workspace split into portfolio, macro, and other, with the deterministic briefing described below. |
| Politics | Congressional stock trades, with an export-for-LLM action. |
| YouTube | Recent videos about your holdings with at least 1,000 views, published in the last 90 days. |
| Dictionary | Reference for market, trading, investing, analysis, formula, chart-pattern, and economic-event terms. |

### App

| Page | What it does |
| --- | --- |
| Settings | General, Workspace, Data, and Diagnostics tabs: clock country and format, obscured pages, navigation order and hidden pages, backup and restore, clear all user data, and crash reports. |

## Project Layout

- `budget_terminal.py`: top-level launcher; auto-runs through `.venv` when available
- `budget_terminal_app/main.py`: Qt application setup, startup loading screen, app icon, and embedded data-service startup
- `budget_terminal_app/app.py`: composed `BudgetTerminalApp` main-window class
- `budget_terminal_app/mixins/`: page, window, and feature behavior
- `budget_terminal_app/workers/`: background data fetchers and signal-driven tasks
- `budget_terminal_app/widgets/`: custom charts, pie/bar charts, and heatmap widgets
- `budget_terminal_app/themes/`: theme tokens and stylesheet helpers
- `budget_terminal_app/data_service/`: shared coordinator plus in-process and compatible FastAPI/HTTP clients
- `budget_terminal_app/services/`: reusable market-data, analytics, and presentation-independent calculations
- `budget_terminal_app/paper_trading/`: sqlite-backed simulated-trading engine and store
- `budget_terminal_app/cache.py`, `persistence.py`, `paths.py`, `constants.py`, `dependencies.py`: shared infrastructure
- `budget_terminal_app/crash_reporting.py`, `error_logging.py`, `backup_bundle.py`, `update_service.py`: diagnostics, backup, and release plumbing
- `scripts/`: smoke tests, with reusable manual probes under `scripts/diagnostics/`
- `packaging/`: PyInstaller specs and build scripts
- `build/`, `dist/`, `release/`: generated build outputs

## Open Multiple Windows

Run the launch command again whenever you want another Budget Terminal window:

```powershell
python budget_terminal.py
```

Each launch starts an independent app process. The windows share the same saved portfolios,
settings, caches, and sqlite state on disk. Avoid changing the same saved setting in two windows at
exactly the same time; for JSON-backed settings, the most recent save wins.

## Development

`.github/workflows/python-ci.yml` is the authoritative list of checks that gate a merge — mirror the
subset that matches what you touched before pushing. The usual local commands:

```powershell
.\.venv\Scripts\python.exe -m ruff check budget_terminal.py budget_terminal_app scripts
```

```powershell
.\.venv\Scripts\python.exe -m compileall -q budget_terminal.py budget_terminal_app
```

```powershell
.\.venv\Scripts\python.exe scripts\test_data_service_transport.py
```

Every `scripts/test_*.py` is a standalone module with its own `__main__` block, run directly. There
is no pytest suite in this checkout, so do not add pytest invocations. Anything that constructs Qt
widgets needs an offscreen platform when run headless:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'; .\.venv\Scripts\python.exe scripts\test_refresh_responsiveness.py
```

`scripts/test_public_repo_privacy.py` runs first in CI and scans every git-tracked file for absolute
user home directories, email addresses, and credential-shaped strings. Keep paths repo-relative in
code, docs, and tests.

Helpful manual probes:

- `.\.venv\Scripts\python.exe scripts\diagnostics\yahoo_data.py AAPL MSFT --include-info`
- `.\.venv\Scripts\python.exe scripts\diagnostics\inspect_cache.py`

UI and data-fetching changes should also be verified with a manual app launch.

## Runtime Flow

`budget_terminal_app/main.py` creates the Qt application, applies the Fusion style, configures
pyqtgraph, shows the startup loading screen, imports `BudgetTerminalApp`, and prepares the main
window before first show. Every launch holds the loading screen for a fixed 30 seconds and then
opens the window, so startup work — page builds, dashboard and startup data, last-session restores,
cache warmup — gets the same predictable time to settle before you can interact. After the first
usable view is visible, the shared data coordinator starts
in-process. If it is unavailable, the app logs the issue and continues with direct worker behavior,
so `self._data_service_client` may legitimately be `None`.

Set `BUDGET_TERMINAL_DATA_TRANSPORT=http` to run the compatible private FastAPI/Uvicorn localhost
transport for diagnostics. The default `inprocess` transport uses the same coordinator contract
without JSON serialization or a loopback socket.

Long-running fetches live in worker objects and report results back through Qt signals so the UI
stays responsive. Writable user data is resolved through `budget_terminal_app/paths.py` instead of
being stored beside the packaged executable.

## Yahoo Finance Pacing

Every Yahoo request is paced by one process-wide gate installed on yfinance's HTTP session by
`budget_terminal_app/services/yahoo_rate_limit.py`. yfinance does no pacing of its own and raises
`YFRateLimitError` on HTTP 429, so the gate smooths bursts to a sustained rate, caps in-flight
requests, and on any 429 halves the rate and starts an exponential cooldown, recovering after a run
of clean responses.

Environment overrides:

- `BUDGET_TERMINAL_YF_REQUESTS_PER_SECOND`
- `BUDGET_TERMINAL_YF_BURST`
- `BUDGET_TERMINAL_YF_MAX_CONCURRENCY`
- `BUDGET_TERMINAL_YF_COOLDOWN_SECONDS` and `BUDGET_TERMINAL_YF_MAX_COOLDOWN_SECONDS`
- `BUDGET_TERMINAL_YF_RATE_LIMIT=0` disables the gate entirely

The gate is installed through the lazy `yf` proxy in `dependencies.py`, so application code must
reach yfinance via `from ..dependencies import yf`. A direct `import yfinance` bypasses the gate.

## News Briefing

The News Hub briefing is generated inside the app and does not use an LLM.

- Briefings are generated from headline text, ticker, source, time, and category
- Full briefings auto-refresh when news updates load
- Clicking a headline row produces a single-item summary
- `Generate Briefing` reruns the deterministic digest manually
- Output includes overall tone, theme counts, portfolio names, macro drivers, latest headlines, notable headlines, and headline-only cautions

## Windows Executable Build

This is a PySide6 desktop GUI app, so the standard packaging target is a windowed PyInstaller build
from `budget_terminal.py`.

Build the executable package:

```powershell
.\packaging\build_exe.bat
```

The build script activates `.venv`, upgrades the packaging tools, installs the pinned runtime and
development requirements, removes old `build/` output and only the current-version `dist/` target,
builds from `packaging\budget_terminal.spec`, and creates `release\BudgetTerminal-v*-windows.zip`.
See `packaging/PACKAGING.md` for the one-dir build flow, release outputs, and troubleshooting notes.

`budget_terminal_app/update_service.py` implements release-update plumbing against GitHub Releases
and is covered by `scripts/test_update_service.py`, but no UI currently calls it, and no release has
been published — updating today means replacing the executable by hand.

## Crash Diagnostics

Settings -> Diagnostics -> Crash Reports lists every crash the app recorded, previews the selected
report, and opens the folder holding them. Files live under
`%LOCALAPPDATA%\BudgetTerminal\logs\crashes`, and the newest 20 reports are kept
(`MAX_CRASH_REPORTS`).

A report captures the environment, the traceback, every Python thread's stack, and the tail of the
session log. Three sources feed it, so a crash that never reaches Python is still recorded:

- `sys.excepthook` and `threading.excepthook` for unhandled Python exceptions.
- A Qt message handler, which writes the report while `qFatal` is still on the stack — this is what
  catches `QThread: Destroyed while thread is still running` before Qt calls `abort()`.
- `faulthandler`, which writes native stacks to `crashes\native-faults.log` for segfaults and other
  aborts that bypass Python entirely.

Each process also drops a session marker and clears it on a clean exit. A marker left by a process
that is gone becomes a `previous-session-aborted` report on the next launch, so a crash that killed
the process outright still surfaces.

## User Data Safety

Do not commit personal portfolio data, API keys, generated cache databases, or machine-specific
runtime files. Packaged builds store writable app data under `%LOCALAPPDATA%\BudgetTerminal`, with
user-facing document data under `Documents\Budget Terminal User Data` when needed.
