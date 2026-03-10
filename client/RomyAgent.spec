# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs, copy_metadata

# Collect playwright hidden imports and data
playwright_hidden_imports = collect_submodules('playwright')
playwright_datas = collect_data_files('playwright')
playwright_metadata = copy_metadata('playwright')

# Collect playwright_stealth hidden imports and data
stealth_hidden_imports = collect_submodules('playwright_stealth')
stealth_datas = collect_data_files('playwright_stealth')
stealth_metadata = copy_metadata('playwright-stealth')

hidden_imports = [
    'plyer.platforms.win.notification',
    'playwright_stealth',
    'playwright_stealth.stealth'
] + playwright_hidden_imports + stealth_hidden_imports

datas = [] + playwright_datas + stealth_datas + stealth_metadata + playwright_metadata

# Ensure Node.js driver (playwright.cmd, node.exe) is explicitly mapped.
# PyInstaller usually collects these with collect_data_files('playwright'), which is in playwright_datas.
# It places them in "playwright/driver/...".

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# Add splash screen
# Using absolute path resolution is not strictly required here as PyInstaller runs from `client/` directory,
# but to be safe we can use it.
splash = Splash(
    'splash.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    minify_script=True,
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    splash,
    splash.binaries,
    [],
    name='ROMY-Agent-MVP',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
