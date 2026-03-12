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

if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

pyinstaller --noconfirm budget_terminal.spec
if errorlevel 1 exit /b 1

echo.
echo Build complete.
echo Executable folder: dist\BudgetTerminal
echo Main executable: dist\BudgetTerminal\BudgetTerminal.exe
