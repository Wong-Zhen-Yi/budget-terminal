# Packaging Guide

This project ships with `PyInstaller` builds from the top-level launcher `budget_terminal.py`.

## Output

The Windows packaging flow produces:

- `dist\BudgetTerminal-v<version>.exe`
- `release\BudgetTerminal-v<version>-windows.zip`

The version comes from `budget_terminal_app.__version__` (in `budget_terminal_app/__init__.py`).
That single string names both artifacts, so bumping it is part of cutting a release rather than an
afterthought.

The same string is what `budget_terminal_app/update_service.py` matches against: it looks for a
GitHub Release asset named `BudgetTerminal-v<version>.exe`
(`APP_ASSET_PREFIX` + version + `APP_ASSET_SUFFIX`) and treats anything with a higher version as an
update. That plumbing has a smoke test (`scripts/test_update_service.py`) but no UI entry point
calls it yet, so today it only matters for keeping release naming consistent.

## Windows Prerequisites

Create the virtual environment:

```powershell
python -m venv .venv
```

Upgrade the packaging tools, then install the pinned runtime and development dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip==26.1.2 setuptools==83.0.0
.\.venv\Scripts\python.exe -m pip install --upgrade --upgrade-strategy eager -r requirements.txt -r requirements-dev.txt
```

## Windows Build Command

Run the standard packaging script from the repository root:

```powershell
.\packaging\build_exe.bat
```

That script will:

1. Activate `.venv`
2. Upgrade the packaging tools and install `requirements.txt` plus `requirements-dev.txt`
3. Remove old `build\` output and only the current-version `dist\` target
4. Build the executable with `packaging\budget_terminal.spec`
5. Create the release zip in `release\`

## Build Files

Main files involved in packaging:

- `packaging\build_exe.bat`: standard one-file exe build
- `packaging\budget_terminal.spec`: PyInstaller spec for the packaged exe
- `packaging\build_exe_onedir.bat`: optional one-dir build flow
- `packaging\budget_terminal_onedir.spec`: PyInstaller spec for the one-dir build

## User Data

User information is not packaged into the executable.

- The spec bundles application code and assets, not runtime user data
- User-writable data is stored under `%LOCALAPPDATA%\BudgetTerminal`
- Backup exports such as `user_data.json` are runtime files, not bundled files

Before publishing a build, verify you are distributing only:

- the generated `.exe`, or
- the generated release `.zip`

Do not manually add personal data, backup folders, cache files, or backup exports to the release package.

## Recommended Verification

After building:

```powershell
.\.venv\Scripts\python.exe -m compileall -q budget_terminal.py budget_terminal_app
```

Then manually check Windows builds:

1. The app launches from `dist\BudgetTerminal-v<version>.exe`
2. Settings import/export works
3. `Clear All User Data` works
4. No personal backup files were added to `dist\` or `release\`

## Publishing a Release

1. Bump `__version__` in `budget_terminal_app/__init__.py`.
2. Run `.\packaging\build_exe.bat` and complete the verification above.
3. Tag the commit `v<version>` to match the artifact name.
4. Publish a GitHub Release and attach `dist\BudgetTerminal-v<version>.exe` as an asset. The asset
   name has to keep that exact shape, or the update-check logic in `update_service.py` will not
   recognize it.

## Troubleshooting

If the build script fails:

- Confirm `.venv\Scripts\python.exe` exists
- Reinstall dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip==26.1.2 setuptools==83.0.0
.\.venv\Scripts\python.exe -m pip install --upgrade --upgrade-strategy eager -r requirements.txt -r requirements-dev.txt
```

- Delete stale build artifacts and rerun:

```powershell
Remove-Item -Recurse -Force build, dist
.\packaging\build_exe.bat
```

If the executable builds but a feature is missing, rebuild after confirming your code changes are saved and included in the current workspace.
