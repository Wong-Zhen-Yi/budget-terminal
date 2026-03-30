# Budget Terminal v0.826

## Architecture
This project is now organized as a small package around the `BudgetTerminalApp` Qt main window. The root `budget_terminal.py` file stays as a thin launcher so existing run commands continue to work.

## Layout
- `budget_terminal_app/app.py`: composed `BudgetTerminalApp` class.
- `budget_terminal_app/mixins/`: page-specific and feature-specific window behavior split into focused mixins.
- `budget_terminal_app/workers/`: background Qt workers for market data, fundamentals, news, calendar events, and Polygon/Massive data.
- `budget_terminal_app/widgets/`: custom chart and pie-chart widgets.
- `budget_terminal_app/persistence.py`: JSON persistence helpers and numeric formatting.
- `budget_terminal_app/cache.py`: SQLite cache manager.
- `budget_terminal_app/constants.py`: color palettes, sector definitions, table metadata, and sentiment vocabularies.
- `budget_terminal_app/dependencies.py`: shared imports and logging setup.

## Runtime Flow
`main.py` creates the Qt application and palette, then instantiates `BudgetTerminalApp`. The main window delegates page initialization and updates to mixins. Long-running data fetches stay in worker objects and report results back through Qt signals, preserving the original UI behavior.

## Development Notes
The refactor is structural only: data files, launch command, and worker/page behavior remain unchanged. New modules were kept small so page logic can be edited in isolation, and the launcher remains compatible with `python budget_terminal.py`.

## Windows .exe Build
This is a `PyQt6` desktop GUI app, so the recommended packaging target is a windowed PyInstaller build using the top-level launcher `budget_terminal.py`.

The default build is a `one-file` executable.
- The output is a single versioned executable such as `BudgetTerminal-v0.826.exe` under `dist\`.
- Startup can be slower than a one-folder build because the bundled app unpacks at launch.
- The build still runs as a windowed/no-console desktop application.

### Build prerequisites
- Windows with Python 3.13+ available as `py` or `python`
- Internet access the first time so `pip` can install build dependencies

### Build command
Run:

```bat
build_exe.bat
```

The script will:
- create `.venv` if needed
- install runtime requirements plus `pyinstaller`
- remove old `build/` and `dist/` folders
- create or replace the current version's `release\BudgetTerminal-v*-windows.zip` archive while keeping older release zips
- build the packaged app from `budget_terminal.spec` as a single executable
- create a versioned release zip containing the new executable

### Build output
After a successful build, the distributable app will be in:

```text
dist\
```

The main executable will be:

```text
dist\BudgetTerminal-v0.826.exe
```

The release archive will be:

```text
release\BudgetTerminal-v0.826-windows.zip
```

### Notes for packaged runs
- The app is built as windowed/no-console.
- Bundled assets such as `budget_terminal_app/assets/qr-code.png` are embedded into the packaged executable.
- User-writable files are stored under `%LOCALAPPDATA%\BudgetTerminal` instead of beside the executable. This includes:
  - `portfolio.json`
  - `portfolio_tracker.json`
  - `options_tracker.json`
  - `net_worth.json`
  - `config.json`
  - `fundamentals_config.json`
  - `p9_config.json`
  - `budget_cache.db`
  - screenshots created from the app

### Rebuilding after code changes
After updating the source, rerun:

```bat
build_exe.bat
```

That regenerates the versioned executable in `dist\`, for example `dist\BudgetTerminal-v0.826.exe`, and updates the matching versioned release zip in `release\` without deleting older archives.
