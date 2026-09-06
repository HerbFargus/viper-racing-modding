# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Viper Racing Mod Manager (single-file build).

Bundles the vrmod package plus the three tricky pieces the app needs at runtime:
  - vrmod/assets/  (three.min.js and the slot icons) via collect_data_files,
  - capstone's native lib (vrmod.vertexbuffer) via collect_dynamic_libs,
  - pythonnet/clr for pywebview's Edge/WinForms backend (hidden import; the
    pywebview + pythonnet PyInstaller hooks handle the rest).

console=False -- it's a GUI app. (Set to True temporarily if you need to see a
startup traceback while debugging a build.)
"""
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

datas = collect_data_files("vrmod")
binaries = collect_dynamic_libs("capstone")

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=["clr"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
# Single-file build: fold binaries + datas into the EXE (no COLLECT). On launch
# PyInstaller unpacks to a temp dir; assets still resolve via Path(__file__)/assets
# because the package tree is recreated there. Slightly slower first launch than
# one-folder, but it ships as one .exe -- what people expect for distribution.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ViperModManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon="icon.ico",
)
