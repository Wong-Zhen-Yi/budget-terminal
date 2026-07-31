# Launch Budget Terminal Without an Agent

This guide is for Windows users who already have the Budget Terminal project folder and want to run the app directly. You do not need Codex, MCP, or any agent tools for these steps.

## 1. Install Python

1. Go to [python.org Windows downloads](https://www.python.org/downloads/windows/).
2. Download the latest stable Python installer.
3. Open the installer.
4. Check **Add python.exe to PATH** on the first installer screen.
5. Click **Install Now** and wait for it to finish.

## 2. Open the Project Folder in PowerShell

1. Open the folder:

   ```text
   %USERPROFILE%\Python Applications\budget-terminal
   ```

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

Run this command once:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip==26.1.2 setuptools==83.0.0
.\.venv\Scripts\python.exe -m pip install --upgrade --upgrade-strategy eager -r requirements.txt
```

This downloads and installs everything Budget Terminal needs.

## 5. Launch the App

Run this command:

```powershell
python budget_terminal.py
```

Budget Terminal should open as a desktop app.

## Next Time

After the setup is done, open PowerShell in the project folder and run:

```powershell
python budget_terminal.py
```

## Troubleshooting

- If PowerShell says `python` is not recognized, reinstall Python and make sure **Add python.exe to PATH** is checked.
- If the app says a dependency is missing, run this again:

  ```powershell
  .\.venv\Scripts\python.exe -m pip install --upgrade pip==26.1.2 setuptools==83.0.0
  .\.venv\Scripts\python.exe -m pip install --upgrade --upgrade-strategy eager -r requirements.txt
  ```

- If the app does not open, launch it from PowerShell instead of double-clicking files. PowerShell will keep the error message visible.
