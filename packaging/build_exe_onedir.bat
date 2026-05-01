@echo off
setlocal

cd /d "%~dp0\.."

set "VENV_DIR=.venv"

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo.
    echo Missing build environment: %VENV_DIR%
    echo Create it and install the build dependencies first:
    echo   python -m venv %VENV_DIR%
    echo   %VENV_DIR%\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
    exit /b 1
)

call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 exit /b 1

python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 exit /b 1

for /f "delims=" %%i in ('python -c "from budget_terminal_app import __version__; print(__version__)"') do set "APP_VERSION=%%i"
set "APP_BASE=BudgetTerminal-v%APP_VERSION%"
set "APP_EXE=%APP_BASE%.exe"
set "APP_DIR=dist\%APP_BASE%"
set "APP_ZIP=%APP_BASE%-windows-onedir.zip"

if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

pyinstaller --noconfirm packaging\budget_terminal_onedir.spec
if errorlevel 1 exit /b 1

if not exist "%APP_DIR%\%APP_EXE%" (
    echo.
    echo Expected build output was not found: %APP_DIR%\%APP_EXE%
    exit /b 1
)

if not exist "release" mkdir "release"

python -c "from pathlib import Path; from zipfile import ZipFile, ZIP_DEFLATED; root = Path(r'%APP_DIR%'); zip_path = Path('release') / r'%APP_ZIP%'; zip_path.unlink(missing_ok=True); zf = ZipFile(zip_path, 'w', compression=ZIP_DEFLATED); [zf.write(path, arcname=str(path.relative_to(root.parent))) for path in root.rglob('*') if path.is_file()]; zf.close()"
if errorlevel 1 exit /b 1

echo.
echo Build complete.
echo App folder: %APP_DIR%
echo Release archive: release\%APP_ZIP%
