@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 exit /b 1

python -m pip install --upgrade pip
if errorlevel 1 exit /b 1

python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 exit /b 1

for /f "delims=" %%i in ('python -c "from budget_terminal_app import __version__; print(__version__)"') do set "APP_VERSION=%%i"
set "APP_EXE=BudgetTerminal-v%APP_VERSION%.exe"
set "APP_ZIP=BudgetTerminal-v%APP_VERSION%-windows.zip"

if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

pyinstaller --noconfirm budget_terminal.spec
if errorlevel 1 exit /b 1

if not exist "release" mkdir "release"

python -c "from pathlib import Path; from zipfile import ZipFile, ZIP_DEFLATED; exe_path = Path('dist') / r'%APP_EXE%'; zip_path = Path('release') / r'%APP_ZIP%'; zip_path.unlink(missing_ok=True); zf = ZipFile(zip_path, 'w', compression=ZIP_DEFLATED); zf.write(exe_path, arcname=exe_path.name); zf.close()"
if errorlevel 1 exit /b 1

echo.
echo Build complete.
echo Main executable: dist\%APP_EXE%
echo Release archive: release\%APP_ZIP%
