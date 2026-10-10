# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Viper Racing Mod Manager on Linux (one-folder build).

The output folder (dist/ViperModManager/) is not shipped as-is: it becomes the
inside of the AppImage, which scripts/build_appimage.sh wraps around it. Run that
script rather than this spec directly (it sets up the venv with the Qt backend).

Differences from the Windows spec (viper-mod-manager.spec):
  - one-folder, not one-file: the AppImage is already a single file, and a
    one-file build inside it would unpack ~250 MB of Qt to /tmp on every launch;
  - the web view is pywebview's Qt backend (PyQt6 + PyQt6-WebEngine, bundled
    whole by PyInstaller's PyQt6 hooks) instead of Edge WebView2 via pythonnet,
    so no `clr` hidden import;
  - no .ico (the AppImage carries icon.png + a .desktop file; the window icon is
    icon.png, bundled at the top of the tree for desktop/app.py to find);
  - the Windows engine binaries (vrmod/assets/modern_engine/*.dll, *.exe) are
    left out; the Linux engine under modern_engine/linux/ is kept. (The Windows
    spec excludes modern_engine/linux/ in turn.)
"""
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

APP_DIR = SPECPATH                        # desktop/  (provided by PyInstaller)
ROOT = os.path.dirname(APP_DIR)           # repo root, where vrmod/ lives

# PyInstaller drops a module that will not compile and builds anyway: v1.6.0
# shipped without vrmod.cli (an IndentationError), and with it every Save in
# the app. So a broken source file stops the build here instead.
import py_compile
for _src in sorted(os.listdir(os.path.join(ROOT, "vrmod"))):
    if _src.endswith(".py"):
        py_compile.compile(os.path.join(ROOT, "vrmod", _src), doraise=True)
sys.path.insert(0, ROOT)                  # so collect_data_files("vrmod") resolves

datas = collect_data_files(
    "vrmod",
    excludes=["assets/modern_engine/*.dll", "assets/modern_engine/*.exe"])
datas.append((os.path.join(APP_DIR, "icon.png"), "."))
binaries = collect_dynamic_libs("capstone")

a = Analysis(
    [os.path.join(APP_DIR, "app.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    # pywebview picks its backend at runtime; app.py asks for "qt" when frozen
    # on Linux. qtpy resolves PyQt6 by import at runtime, so name it.
    hiddenimports=["webview.platforms.qt", "qtpy", "PyQt6.QtWebEngineWidgets",
                   "PyQt6.QtWebEngineCore", "PyQt6.QtWebChannel", "PyQt6.QtNetwork"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Other pywebview backends / other Qt bindings -- keep them out even if the
    # build machine happens to have them installed.
    excludes=["gi", "webview.platforms.gtk", "webview.platforms.cef",
              "webview.platforms.winforms", "webview.platforms.edgechromium",
              "clr", "PyQt5", "PySide2", "PySide6", "tkinter"],
    noarchive=False,
)


# --- Trim the bundle -----------------------------------------------------------
# PyInstaller's PyQt6 hooks are generous: QtWebEngine drags in the QtQml/QtQuick
# Python modules, and with them every QML plugin (Quick3D, Multimedia, Controls,
# ...) and the GTK3 platform theme (which pulls the whole GTK stack). A
# QWebEngineView in a QMainWindow needs none of it.
#
# DROP_DIRS / DROP_FILES go first; then any shared library that nothing left in
# the bundle links against is dropped too (the "unreachable" pass).
# SYSTEM_LIBS are left to the target system on purpose, as AppImages usually do:
# they are on every desktop Linux, are backward compatible, and bundling the
# build machine's copy can break the system's own GPU driver stack, which gets
# loaded into the same process (Mesa wants the system's newer libstdc++,
# libgbm/libdrm must match the installed Mesa, fontconfig must read the system's
# config format, glib must match the system's GIO modules).
DROP_DIRS = ("PyQt6/Qt6/qml/",)
DROP_FILES = {"PyQt6/Qt6/plugins/platformthemes/libqgtk3.so"}
SYSTEM_LIBS = {
    "libstdc++.so.6", "libgcc_s.so.1",
    "libglib-2.0.so.0", "libgobject-2.0.so.0", "libgio-2.0.so.0",
    "libgmodule-2.0.so.0", "libgthread-2.0.so.0",
    "libfontconfig.so.1", "libfreetype.so.6", "libharfbuzz.so.0", "libexpat.so.1",
    "libgbm.so.1", "libdrm.so.2", "libasound.so.2",
    "libdbus-1.so.3", "libudev.so.1", "libsystemd.so.0",
}


def _norm(dest):
    return dest.replace(os.sep, "/")


def _keep_entry(entry):
    dest = _norm(entry[0])
    if dest.startswith(DROP_DIRS) or dest in DROP_FILES:
        return False
    if os.path.basename(dest) in SYSTEM_LIBS:
        return False
    # Qt's own .qm UI translations (the Chromium locales under
    # translations/qtwebengine_locales/ are kept).
    if dest.startswith("PyQt6/Qt6/translations/") and dest.endswith(".qm"):
        return False
    return True


a.binaries = [e for e in a.binaries if _keep_entry(e)]
a.datas = [e for e in a.datas if _keep_entry(e)]


def _prune_unreachable(binaries):
    """Drop plain shared libraries (bundle root, Qt6/lib) that nothing kept links
    against. Roots are everything else: Python extension modules, Qt plugins,
    capstone, QtWebEngineProcess."""
    from PyInstaller.depend.bindepend import get_imports

    def is_lib(dest):
        d = os.path.dirname(dest)
        return d in ("", ".", "PyQt6/Qt6/lib")

    libs = {os.path.basename(_norm(e[0])): e for e in binaries if is_lib(_norm(e[0]))}
    roots = [e for e in binaries if not is_lib(_norm(e[0]))]
    needed, todo = set(), [e[1] for e in roots]
    while todo:                    # ldd already reports the transitive set, but a
        src = todo.pop()           # lib may resolve outside the bundle, so walk ours
        for name, _ in get_imports(src):
            base = os.path.basename(name)
            if base in libs and base not in needed:
                needed.add(base)
                todo.append(libs[base][1])
    keep = [e for e in binaries
            if not is_lib(_norm(e[0])) or os.path.basename(_norm(e[0])) in needed
            or os.path.basename(_norm(e[0])).startswith("libpython")]
    dropped = sorted(n for n in set(libs) - needed if not n.startswith("libpython"))
    print(f"[vrmod spec] dropped {len(dropped)} unreachable libs: {' '.join(dropped)}")
    return keep


a.binaries = _prune_unreachable(a.binaries)

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
