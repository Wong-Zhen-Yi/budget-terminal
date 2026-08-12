# Budget Terminal

Budget Terminal is a Windows-focused PyQt6 desktop application for portfolio tracking, market research, options, news, fundamentals, valuation, charts, and related investing workflows.

## Requirements

- Windows 10 or Windows 11
- Python 3.11 or newer
- Internet access for live market and research data

## Setup

Open PowerShell in the repository folder and create a local virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run

```powershell
.\.venv\Scripts\python.exe budget_terminal.py
```

Run the same command again whenever you want another independent Budget Terminal window.

## Repository Contents

- `budget_terminal.py`: application launcher
- `budget_terminal_app/`: application code and runtime assets
- `requirements.txt`: pinned runtime dependencies

## User Data Safety

Writable application data is stored outside the repository under `%LOCALAPPDATA%\BudgetTerminal` and the user-facing Budget Terminal documents folder. Do not commit portfolio data, API keys, caches, logs, backups, or other machine-specific runtime files.
