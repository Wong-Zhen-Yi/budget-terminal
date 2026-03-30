# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Budget Terminal is a PyQt6 desktop financial trading terminal. It fetches market data from Yahoo Finance, Polygon.io, and news APIs, caches it in SQLite, and provides portfolio tracking, fundamentals analysis, options chain viewing, charting, and news sentiment analysis. Packaged as a single Windows executable via PyInstaller.

## Commands

```bash
# Setup
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt

# Run the app
python budget_terminal.py

# Quick syntax check
python -m compileall budget_terminal.py

# Smoke-test options fetch
python test_options_fetch.py

# Build Windows executable (requires Python 3.13+, outputs dist\BudgetTerminal-v0.826.exe and release\BudgetTerminal-v0.826-windows.zip)
build_exe.bat
```

There is no pytest suite. Ad-hoc test scripts at the root (`test_*.py`, `check_*.py`, `debug_*.py`, `inspect_cache.py`) serve as smoke tests. Name new test scripts `test_<feature>.py` to match the existing pattern.

## Architecture

### Mixin-Based Composition

`BudgetTerminalApp` (in `budget_terminal_app/app.py`) inherits from ~22 mixins plus `QMainWindow`. Each mixin in `budget_terminal_app/mixins/` owns a page or feature (dashboard, portfolio, options, news, settings, etc.). This is the core architectural pattern — new features should be added as new mixins, not by expanding existing ones.

The mixin inheritance order in `app.py` matters (Python MRO). It follows a logical sequence: Theme → Window (bootstrap/setup/lifecycle) → Data Pages → Feature Pages → `QMainWindow`. New mixins should be inserted in the appropriate position in this chain.

### Import Chain

Mixins and workers should import from `dependencies.py`, not directly from PyQt6 or third-party libraries. The chain is:

1. `compat.py` — centralizes all PyQt6 and third-party imports, sets up logging, defines `YF_LOCK`
2. `dependencies.py` — re-exports from `compat` plus utility modules (persistence, cache, constants, workers, widgets)
3. Mixins/workers import from `dependencies`

### Startup Flow

`budget_terminal.py` (thin launcher) → `budget_terminal_app/main.py` (creates `QApplication`, sets Fusion style) → `BudgetTerminalApp.__init__()` → `WindowSetupMixin.init_ui()` builds the central widget, navigation bar, and page stack → individual mixin `_init_*_page()` methods create each page → `_register_navigation_pages()` connects nav buttons to the `QStackedWidget`.

### Worker Threading

Background data fetching uses Qt worker objects in `budget_terminal_app/workers/`. Workers emit `finished(dict)` and `error(str)` signals back to the main window. Never do network I/O on the main thread. Yahoo Finance calls must use `YF_LOCK` (defined in `compat.py`) for thread safety.

### Key Modules

- `compat.py` — centralizes all PyQt6 and third-party imports with logging
- `dependencies.py` — re-exports from compat for convenient importing throughout mixins
- `constants.py` — color palettes, sector definitions, table metadata, sentiment vocabularies
- `persistence.py` — JSON load/save, portfolio calculations, numeric formatting
- `cache.py` — SQLite cache manager with per-ticker tables (`cache_{safe_ticker}_{interval}`) and metadata tracking; sanitizes special chars in ticker names (`^` → `IDX_`, `=` → `FX_`)
- `paths.py` — resolves file paths for both development and PyInstaller-frozen execution; use `resource_path()` for read-only bundled assets, `user_data_dir()` for writable user data

### Data Storage

User data lives in `%LOCALAPPDATA%\BudgetTerminal` (when frozen) or beside the script (in dev): `portfolio.json`, `portfolio_tracker.json`, `options_tracker.json`, `net_worth.json`, `config.json`, `fundamentals_config.json`, `p9_config.json`, `budget_cache.db`.

The app supports 3 fixed portfolio slots (`portfolio_1`, `portfolio_2`, `portfolio_3`). Portfolio holdings are in `portfolio.json`, cost-basis tracking in `portfolio_tracker.json`, and option positions in `options_tracker.json`.

## Code Style

- 4-space indentation, `snake_case` functions/variables, `PascalCase` classes, `UPPERCASE` constants
- No configured formatter — preserve existing layout and import style
- Keep helpers close to the feature they support; prefer small targeted edits over broad reformatting
- Do not commit portfolio data, API credentials, or cache files
- Commit messages: short imperative subjects (e.g., `Fix tracker totals rounding`, `Add cache guard for options fetch`)
