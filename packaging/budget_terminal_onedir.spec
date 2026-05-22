# -*- mode: python ; coding: utf-8 -*-

import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

project_root = os.path.abspath('.')
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from budget_terminal_app import __version__

app_name = f'BudgetTerminal-v{__version__}'
manifest_path = os.path.join(project_root, 'packaging', 'budget_terminal_dpi_manifest.xml')

datas = collect_data_files('budget_terminal_app', includes=['assets/app_icon.png'])
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

a = Analysis(
    ['budget_terminal.py'],
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
    [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon='budget_terminal_app/assets/app_icon.ico',
    manifest=manifest_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=app_name,
)
