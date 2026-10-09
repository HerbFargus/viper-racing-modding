#!/usr/bin/env bash
# Build dist/ViperModManager-x86_64.AppImage -- the Linux counterpart of the
# Windows ViperModManager.exe: one file, no install, double-click to run.
#
# Run on x86_64 Linux with glibc no newer than the oldest system you want to
# support -- the AppImage needs at least the build machine's glibc. We build on
# Ubuntu 22.04 (glibc 2.35), so it runs on Ubuntu 22.04+ / Mint 21+ / SteamOS 3.
# From Windows, WSL works:
#     wsl -d Ubuntu-22.04 -- bash scripts/build_appimage.sh
#
# One-time packages on the build machine (Ubuntu 22.04):
#     sudo add-apt-repository ppa:deadsnakes/ppa   # Python 3.14, as the Windows build uses:
#                                                   # vrmod relies on 3.13+ features in places
#     sudo apt install python3.14 python3.14-venv python3.14-dev binutils file wget \
#         libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 \
#         libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 \
#         libxcb-xinerama0 libxcb-xkb1 libegl1 libgl1 libnss3 libxcomposite1 \
#         libxdamage1 libxrandr2 libxtst6 libasound2 libfontconfig1 libdbus-1-3 \
#         libxkbfile1 libxshmfence1 libgbm1
# (The libxcb-*/libxkb*/libnss3 set is what Qt's xcb plugin and Qt WebEngine
# link against; PyInstaller copies whichever of them it finds into the bundle,
# so they must be present here for the AppImage to not need them on the target.
# libxcb-cursor0 in particular is NOT on a stock Ubuntu desktop.)
#
# What it does:
#   1. venv under $BUILD_DIR with desktop/linux/requirements-linux.txt (pinned:
#      pywebview's Qt backend = PyQt6 + PyQt6-WebEngine, capstone, PyInstaller);
#   2. PyInstaller with desktop/viper-mod-manager-linux.spec (one-folder);
#   3. an AppDir around it (AppRun, .desktop, icon);
#   4. appimagetool (pinned release, sha256-checked) + the pinned type-2 runtime
#      (static, needs no libfuse2 on the target) -> dist/ViperModManager-x86_64.AppImage.
#
# Env knobs: BUILD_DIR (default ~/.cache/vrmod-appimage -- kept off /mnt/c so a
# WSL build isn't crawling over 9P), OUT_DIR (default <repo>/dist).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$HOME/.cache/vrmod-appimage-py314}"
OUT_DIR="${OUT_DIR:-$REPO/dist}"
PYTHON="${PYTHON:-python3.14}"                       # (the Windows build is 3.14 too)
APP=ViperModManager

# Pinned tools. The sha256s are the digests GitHub publishes for these release
# assets (api.github.com/repos/AppImage/<repo>/releases -> assets[].digest).
APPIMAGETOOL_URL=https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage
APPIMAGETOOL_SHA256=ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
RUNTIME_URL=https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64
RUNTIME_SHA256=2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d

[ "$(uname -m)" = x86_64 ] || { echo "build_appimage.sh: x86_64 only" >&2; exit 1; }
echo "== repo $REPO"
echo "== build dir $BUILD_DIR (glibc $(ldd --version | head -1 | awk '{print $NF}'))"
mkdir -p "$BUILD_DIR/tools" "$OUT_DIR"

fetch() {  # fetch URL SHA256 DEST
    local url=$1 sum=$2 dest=$3
    if [ ! -f "$dest" ] || ! echo "$sum  $dest" | sha256sum -c --status; then
        echo "== downloading $url"
        wget -q -O "$dest.part" "$url"
        echo "$sum  $dest.part" | sha256sum -c - >/dev/null \
            || { echo "checksum mismatch for $url" >&2; rm -f "$dest.part"; exit 1; }
        mv "$dest.part" "$dest"
    fi
    chmod +x "$dest"
}
fetch "$APPIMAGETOOL_URL" "$APPIMAGETOOL_SHA256" "$BUILD_DIR/tools/appimagetool-x86_64.AppImage"
fetch "$RUNTIME_URL" "$RUNTIME_SHA256" "$BUILD_DIR/tools/runtime-x86_64"

# --- 1. venv -----------------------------------------------------------------
VENV="$BUILD_DIR/venv"
if [ ! -x "$VENV/bin/python" ]; then
    "$PYTHON" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install -q --upgrade pip
"$VENV/bin/python" -m pip install -q -r "$REPO/desktop/linux/requirements-linux.txt"

# --- 2. PyInstaller (one-folder) -----------------------------------------------
rm -rf "$BUILD_DIR/pyi-dist"
"$VENV/bin/python" -m PyInstaller --noconfirm --clean \
    --workpath "$BUILD_DIR/pyi-work" --distpath "$BUILD_DIR/pyi-dist" \
    "$REPO/desktop/viper-mod-manager-linux.spec"

# --- 3. AppDir -----------------------------------------------------------------
APPDIR="$BUILD_DIR/$APP.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a "$BUILD_DIR/pyi-dist/$APP" "$APPDIR/usr/lib/$APP"
install -m 755 "$REPO/desktop/linux/AppRun" "$APPDIR/AppRun"
install -m 644 "$REPO/desktop/linux/viper-mod-manager.desktop" "$APPDIR/viper-mod-manager.desktop"
install -m 644 "$REPO/desktop/linux/viper-mod-manager.desktop" "$APPDIR/usr/share/applications/"
install -m 644 "$REPO/desktop/icon.png" "$APPDIR/viper-mod-manager.png"
install -m 644 "$REPO/desktop/icon.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/viper-mod-manager.png"
ln -s viper-mod-manager.png "$APPDIR/.DirIcon"
if command -v desktop-file-validate >/dev/null; then
    desktop-file-validate "$APPDIR/viper-mod-manager.desktop"
fi

# --- 4. AppImage ---------------------------------------------------------------
OUT="$OUT_DIR/$APP-x86_64.AppImage"
rm -f "$OUT"
# appimagetool is itself an AppImage; extract-and-run means the build box needs
# no FUSE either (WSL, containers).
ARCH=x86_64 "$BUILD_DIR/tools/appimagetool-x86_64.AppImage" --appimage-extract-and-run \
    --no-appstream --runtime-file "$BUILD_DIR/tools/runtime-x86_64" \
    "$APPDIR" "$OUT"
echo "== built $OUT ($(du -h "$OUT" | cut -f1))"
