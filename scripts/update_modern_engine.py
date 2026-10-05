"""Refresh the bundled modern engine (vrmod/assets/modern_engine/) from a viper-racing-port build.

The modern engine is viper-racing-port's dinput.dll -- a DLL the game loads from its own folder that
lifts the engine's limits and replaces DirectDraw/Direct3D, DirectSound and the Windows input with
OpenGL and SDL2 -- plus the SDL2.dll it needs, and viperport.exe, the standalone loader that runs a v1.0
race.exe on the port's code alone (through that same dinput.dll). vrmod ships them prebuilt; this copies
a fresh build in and records where it came from (SOURCE.txt: the commit and each file's sha256), so the
bundled files are always traceable to a commit.

    python scripts/update_modern_engine.py [path/to/viper-racing-port]

Build viper-racing-port first (hook\\build.bat for dinput.dll and SDL2.dll, loader\\build_loader.bat for
viperport.exe); its working tree must be clean, so the recorded commit is exactly what was built.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "vrmod" / "assets" / "modern_engine"
FILES = ("dinput.dll", "viperport.exe", "SDL2.dll")


def main() -> int:
    port = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "viper-racing-port"
    build = port / "hook" / "build"
    loader = port / "loader" / "build" / "viperport.exe"
    sdl_license = port.parent / "sdl2" / "SDL2-2.32.10" / "LICENSE.txt"
    for f in (build / "dinput.dll", build / "SDL2.dll", loader, sdl_license):
        if not f.is_file():
            print(f"missing {f} -- build viper-racing-port first (hook\\build.bat, loader\\build_loader.bat)")
            return 1
    for f in (build / "dinput.dll", loader):
        if b"viperport" not in f.read_bytes():
            print(f"{f} doesn't carry the viperport mark -- not a viper-racing-port build?")
            return 1
    git = lambda *a: subprocess.run(["git", "-C", str(port), *a], capture_output=True, text=True).stdout.strip()
    if git("status", "--porcelain", "--untracked-files=no"):
        print(f"{port} has uncommitted changes -- commit them so the bundled build is traceable")
        return 1
    commit, date = git("log", "-1", "--format=%H"), git("log", "-1", "--format=%cs")
    DEST.mkdir(parents=True, exist_ok=True)
    shutil.copy2(build / "dinput.dll", DEST / "dinput.dll")
    shutil.copy2(build / "SDL2.dll", DEST / "SDL2.dll")
    shutil.copy2(loader, DEST / "viperport.exe")
    shutil.copy2(sdl_license, DEST / "SDL2-LICENSE.txt")
    sha = {n: hashlib.sha256((DEST / n).read_bytes()).hexdigest() for n in FILES}
    (DEST / "SOURCE.txt").write_text(
        "The modern engine: viper-racing-port's dinput.dll, its standalone loader viperport.exe (v1.0 only),\n"
        "and SDL2 2.32.10 (zlib licence, SDL2-LICENSE.txt).\n"
        f"viper-racing-port commit {commit} ({date})\n"
        + "".join(f"sha256 {h}  {n}\n" for n, h in sha.items()))
    print(f"bundled viper-racing-port {commit[:7]} ({date}) into {DEST.relative_to(ROOT)}: {', '.join(FILES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
