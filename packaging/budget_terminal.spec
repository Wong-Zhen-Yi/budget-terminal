# -*- mode: python ; coding: utf-8 -*-

import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

project_root = os.path.abspath('.')
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from budget_terminal_app import __version__

app_name = f'BudgetTerminal-v{__version__}'
icon_path = os.path.join(project_root, 'budget_terminal_app', 'assets', 'app_icon.ico')
manifest_path = os.path.join(project_root, 'packaging', 'budget_terminal_dpi_manifest.xml')

datas = collect_data_files('budget_terminal_app', includes=['assets/app_icon.png', 'assets/world_countries_50m.json'])
datas += collect_data_files('tzdata')

hiddenimports = collect_submodules('yfinance')
hiddenimports += collect_submodules('pandas_market_calendars')
hiddenimports += collect_submodules('exchange_calendars')
hiddenimports += collect_submodules('pyqtgraph')
hiddenimports += collect_submodules('fastapi')
hiddenimports += collect_submodules('uvicorn')
hiddenimports += collect_submodules('starlette')
hiddenimports += collect_submodules('pydantic')
hiddenimports += collect_submodules('httpx')
hiddenimports += collect_submodules('yt_dlp')
hiddenimports += [
    'PyQt6.QtNetwork',
    'pandas',
    'pyqtgraph',
    'requests',
    'yfinance',
    'fastapi',
    'uvicorn',
    'starlette',
    'pydantic',
    'httpx',
    'yt_dlp',
]

launcher_path = os.path.join(project_root, 'budget_terminal.py')

a = Analysis(
    [launcher_path],
    pathex=[project_root],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    exclude_binaries=False,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=icon_path,
    manifest=manifest_path,
)
