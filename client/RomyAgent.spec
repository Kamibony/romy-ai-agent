# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import playwright_stealth
from PyInstaller.utils.hooks import collect_all

# 1. Exhaustive collection for core dependencies
playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all('playwright')
stealth_datas, stealth_binaries, stealth_hiddenimports = collect_all('playwright_stealth')

# 2. Deterministic mapping for unhooked JS assets
stealth_package_dir = os.path.dirname(playwright_stealth.__file__)
stealth_js_dir = os.path.join(stealth_package_dir, 'js')
explicit_stealth_datas = [(stealth_js_dir, 'playwright_stealth/js')]

# 3. Unified Merging
hidden_imports = ['plyer.platforms.win.notification'] + playwright_hiddenimports + stealth_hiddenimports
datas = playwright_datas + stealth_datas + explicit_stealth_datas
binaries = playwright_binaries + stealth_binaries

# Ensure Node.js driver (playwright.cmd, node.exe) is explicitly mapped.
# PyInstaller usually collects these with collect_data_files('playwright'), which is in playwright_datas.
# It places them in "playwright/driver/...".

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
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
