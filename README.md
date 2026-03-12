# Budget Terminal v0.6

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
