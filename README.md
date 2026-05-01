# Budget Terminal v0.829

## Architecture
This project is organized as a small package around the `BudgetTerminalApp` Qt main window. The root `budget_terminal.py` file remains the launcher so existing run commands still work.

## Layout
- `budget_terminal_app/app.py`: composed `BudgetTerminalApp` class
- `budget_terminal_app/mixins/`: page-specific and feature-specific window behavior
- `budget_terminal_app/workers/`: background workers for market data, fundamentals, news, calendar events, and Polygon/Massive data
- `budget_terminal_app/widgets/`: custom chart and pie-chart widgets
- `budget_terminal_app/persistence.py`: JSON persistence helpers and numeric formatting
- `budget_terminal_app/cache.py`: SQLite cache manager
- `budget_terminal_app/constants.py`: color palettes, sector definitions, table metadata, and sentiment vocabularies
- `budget_terminal_app/dependencies.py`: shared imports and logging setup

## Runtime Flow
`main.py` creates the Qt application and palette, then instantiates `BudgetTerminalApp`. The main window delegates page initialization and updates to mixins. Long-running data fetches stay in worker objects and report results back through Qt signals so the UI stays responsive.

## News Briefing
The News Hub briefing is built into the app and does not use an LLM.

- The briefing is generated from headline text, ticker, source, time, and category only.
- Full briefings auto-refresh when news updates load.
- Clicking a headline row still produces a single-item summary.
- `Generate Briefing` reruns the full deterministic digest manually.
- The output includes overall tone, theme counts, portfolio names, macro drivers, latest headlines, notable headlines, and brief headline-only cautions.

## Development
Install the app dependencies with:

```powershell
python -m pip install -r requirements.txt
```

Run the desktop app with:

```powershell
python budget_terminal.py
```

## Windows .exe Build
This is a `PyQt6` desktop GUI app, so the recommended packaging target is a windowed PyInstaller build using the top-level launcher `budget_terminal.py`.

### Build prerequisites
- A working virtual environment at `.venv`
- `pyinstaller` installed in that environment

If the environment does not exist yet:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
```

### Build command
Run:

```bat
packaging\build_exe.bat
```

The script will:
- activate `.venv`
- install `requirements.txt` plus `pyinstaller`
- remove old `build/` and `dist/` folders
- build the packaged app from `packaging\budget_terminal.spec`
- create `release\BudgetTerminal-v*-windows.zip`

### Packaged run notes
- The app is built as windowed/no-console.
- Only required application assets are embedded into the packaged executable.
- User-writable files are stored under `%LOCALAPPDATA%\BudgetTerminal` instead of beside the executable.
