# Launch Budget Terminal Without an Agent

This guide is for Windows users who have the Budget Terminal project folder and want to run the app
directly. You do not need Codex, MCP, or any agent tools for these steps.

If someone handed you a packaged `BudgetTerminal-v<version>.exe`, you can skip this entire guide:
double-click the executable, and allow it past the Windows SmartScreen warning shown for unsigned
builds. Everything below is for running from the source folder. Building that executable yourself is
covered in `packaging/PACKAGING.md`.

## 1. Install Python

1. Go to [python.org Windows downloads](https://www.python.org/downloads/windows/).
2. Download the latest stable Python installer.
3. Open the installer.
4. Check **Add python.exe to PATH** on the first installer screen.
5. Click **Install Now** and wait for it to finish.

## 2. Open the Project Folder in PowerShell

1. Open the folder you cloned or extracted the project into. It is the folder containing
   `budget_terminal.py`.
2. Click the address bar at the top of File Explorer.
3. Type:

   ```powershell
   powershell
   ```

4. Press **Enter**. A PowerShell window should open inside the project folder.

## 3. Create the App Environment

Run this command once:

```powershell
python -m venv .venv
```

This creates a local Python environment for the app.

## 4. Install Dependencies

Run these two commands once:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip==26.1.2 setuptools==83.0.0
```

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade --upgrade-strategy eager -r requirements.txt
```

This downloads and installs everything Budget Terminal needs to run. You only need the extra
`requirements-dev.txt` packages if you plan to build the Windows executable.

## 5. Launch the App

Run this command:

```powershell
.\.venv\Scripts\python.exe budget_terminal.py
```

Budget Terminal should open as a desktop app.

Plain `python budget_terminal.py` works too: when a `.venv` folder exists, the launcher restarts
itself inside that environment automatically. Set `BUDGET_TERMINAL_SKIP_LOCAL_VENV=1` if you ever
need to stop it from doing that.

## Open Multiple Windows

Run the launch command again whenever you want another Budget Terminal window:

```powershell
.\.venv\Scripts\python.exe budget_terminal.py
```

Each launch starts an independent app process. The windows share the same saved portfolios,
settings, caches, and sqlite state on disk. Avoid changing the same saved setting in two windows at
exactly the same time; for JSON-backed settings, the most recent save wins.

## Next Time

After the setup is done, open PowerShell in the project folder and run:

```powershell
.\.venv\Scripts\python.exe budget_terminal.py
```

## Troubleshooting

- If PowerShell says `python` is not recognized, reinstall Python and make sure **Add python.exe to
  PATH** is checked.
- If the app says a dependency is missing, run the two install commands from step 4 again.
- If the app does not open, launch it from PowerShell instead of double-clicking files. PowerShell
  will keep the error message visible.
- If the app opens but tables stay empty or show rate-limit errors, wait a minute and refresh the
  page. Market data comes from Yahoo Finance, and the app deliberately slows itself down after a
  rate-limit response rather than hammering the service.
- If the app closed unexpectedly, open **Settings -> Diagnostics -> Crash Reports** on the next
  launch. Reports and session logs live under `%LOCALAPPDATA%\BudgetTerminal\logs`.
