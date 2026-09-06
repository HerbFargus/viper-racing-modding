# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Viper Racing Mod Manager (one-folder build).

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
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ViperModManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ViperModManager",
)
