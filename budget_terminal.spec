# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
from budget_terminal_app import __version__

app_name = f'BudgetTerminal-v{__version__}'

datas = collect_data_files('budget_terminal_app', includes=['assets/*.png'])
datas += collect_data_files('tzdata')

hiddenimports = collect_submodules('yfinance')

a = Analysis(
    ['budget_terminal.py'],
    pathex=[],
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
    icon='budget_terminal_app/assets/app_icon.ico',
)
