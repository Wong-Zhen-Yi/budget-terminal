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

# Build Windows executable (outputs dist\BudgetTerminal-v0.76.exe)
build_exe.bat
```

There is no pytest suite. Ad-hoc test scripts at the root (`test_*.py`, `check_*.py`, `debug_*.py`, `inspect_cache.py`) serve as smoke tests.

## Architecture

### Mixin-Based Composition

`BudgetTerminalApp` (in `budget_terminal_app/app.py`) inherits from ~22 mixins plus `QMainWindow`. Each mixin in `budget_terminal_app/mixins/` owns a page or feature (dashboard, portfolio, options, news, settings, etc.). This is the core architectural pattern — new features should be added as new mixins, not by expanding existing ones.

### Worker Threading

Background data fetching uses Qt worker objects in `budget_terminal_app/workers/`. Workers emit `finished(dict)` and `error(str)` signals back to the main window. Never do network I/O on the main thread.

### Key Modules

- `compat.py` — centralizes all PyQt6 and third-party imports with logging
- `dependencies.py` — re-exports from compat for convenient importing throughout mixins
- `constants.py` — color palettes, sector definitions, table metadata, sentiment vocabularies
- `persistence.py` — JSON load/save, portfolio calculations, numeric formatting
- `cache.py` — SQLite cache manager with per-ticker tables and metadata tracking
- `paths.py` — resolves file paths for both development and PyInstaller-frozen execution

### Data Storage

User data lives in `%LOCALAPPDATA%\BudgetTerminal` (when frozen) or beside the script (in dev): `portfolio.json`, `portfolio_tracker.json`, `options_tracker.json`, `net_worth.json`, `config.json`, `budget_cache.db`.

## Code Style

- 4-space indentation, `snake_case` functions/variables, `PascalCase` classes, `UPPERCASE` constants
- No configured formatter — preserve existing layout and import style
- Keep helpers close to the feature they support; prefer small targeted edits over broad reformatting
- Do not commit portfolio data, API credentials, or cache files
