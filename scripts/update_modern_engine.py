"""Refresh the bundled modern engine (vrmod/assets/modern_engine/) from a viper-racing-port build.

The modern engine is viper-racing-port's dinput.dll -- a DLL the game loads from its own folder that
lifts the engine's limits and replaces DirectDraw/Direct3D, DirectSound and the Windows input with
OpenGL and SDL2 -- plus the SDL2.dll it needs, and viperport.exe, the standalone loader that runs a v1.0
race.exe on the port's code alone (through that same dinput.dll). On Linux it is the native standalone:
`viperport` (a 32-bit ELF), its launcher `viperport.sh`, `lib/libSDL2-2.0.so.0`, README-linux.txt and
LICENSES/, from viper-racing-port's Linux release tarball, kept under linux/. vrmod ships them prebuilt;
this copies a fresh build in and records where it came from (SOURCE.txt: the commit and each file's
sha256), so the bundled files are always traceable to a commit.

    python scripts/update_modern_engine.py [path/to/viper-racing-port]       the Windows files
    python scripts/update_modern_engine.py --linux viperport-linux-*.tar.gz  the Linux files

For Windows, build viper-racing-port first (hook\\build.bat for dinput.dll and SDL2.dll,
loader\\build_loader.bat for viperport.exe); its working tree must be clean, so the recorded commit is
exactly what was built. For Linux, download the release tarball (gh release download <tag> --repo
HerbFargus/viper-racing-port --pattern "viperport-linux-*.tar.gz*"); its .sha256 beside it is checked
when present. Each refresh rewrites its own half of SOURCE.txt and keeps the other half as it was.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "vrmod" / "assets" / "modern_engine"
LINUX_DEST = DEST / "linux"
FILES = ("dinput.dll", "viperport.exe", "SDL2.dll")
LINUX_REQUIRED = ("viperport", "viperport.sh", "lib/libSDL2-2.0.so.0", "README-linux.txt")
LINUX_EXEC = ("viperport", "viperport.sh")
LINUX_HEAD = "Linux:"            # SOURCE.txt: the Linux half starts with this line


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _halves() -> tuple[str, str]:
    """SOURCE.txt as (Windows half, Linux half), either '' when not there yet."""
    src = DEST / "SOURCE.txt"
    text = src.read_text(encoding="utf-8") if src.is_file() else ""
    i = text.find("\n" + LINUX_HEAD)
    if text.startswith(LINUX_HEAD):
        return "", text
    if i < 0:
        return text, ""
    return text[:i + 1].rstrip("\n") + "\n", text[i + 1:]


def _write_source(windows: str, linux: str) -> None:
    (DEST / "SOURCE.txt").write_text(windows + ("\n" if windows and linux else "") + linux,
                                     encoding="utf-8", newline="\n")


def update_windows(port: Path) -> int:
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
    sha = {n: _sha(DEST / n) for n in FILES}
    windows = ("The modern engine: viper-racing-port's dinput.dll, its standalone loader viperport.exe (v1.0 only),\n"
               "and SDL2 2.32.10 (zlib licence, SDL2-LICENSE.txt).\n"
               f"viper-racing-port commit {commit} ({date})\n"
               + "".join(f"sha256 {h}  {n}\n" for n, h in sha.items()))
    _write_source(windows, _halves()[1])
    print(f"bundled viper-racing-port {commit[:7]} ({date}) into {DEST.relative_to(ROOT)}: {', '.join(FILES)}")
    return 0


def update_linux(tarball: Path) -> int:
    """Unpack the Linux release tarball's files into linux/ (the folder inside it stripped), by name --
    nothing outside the package's own layout is written."""
    if not tarball.is_file():
        print(f"no tarball {tarball}")
        return 1
    m = re.match(r"viperport-linux-(\d{4})\.(\d{2})\.(\d{2})-([0-9a-f]{7,40})\.tar\.gz$", tarball.name)
    if not m:
        print(f"{tarball.name} isn't named like a viper-racing-port Linux release (viperport-linux-<date>-<commit>.tar.gz)")
        return 1
    date, commit = f"{m[1]}-{m[2]}-{m[3]}", m[4]
    tar_sha = _sha(tarball)
    check = tarball.with_name(tarball.name + ".sha256")
    if check.is_file():
        want = check.read_text(encoding="utf-8", errors="replace").split()[0].lower()
        if want != tar_sha:
            print(f"{tarball.name}: sha256 {tar_sha} doesn't match {check.name} ({want})")
            return 1
        print(f"{tarball.name}: sha256 matches {check.name}")
    else:
        print(f"(no {check.name} beside it to check against)")
    files: dict[str, bytes] = {}
    with tarfile.open(tarball, "r:gz") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            parts = PurePosixPath(member.name).parts[1:]          # strip the package's top folder
            if not parts or any(p in ("", ".", "..") for p in parts):
                continue
            rel = "/".join(parts)
            if rel in LINUX_REQUIRED or (len(parts) == 2 and parts[0] == "LICENSES"):
                files[rel] = tf.extractfile(member).read()
    missing = [n for n in LINUX_REQUIRED if n not in files]
    if missing:
        print(f"{tarball.name} lacks {', '.join(missing)} -- not a viper-racing-port Linux package?")
        return 1
    if not files["viperport"].startswith(b"\x7fELF") or b"viperport" not in files["viperport"]:
        print("its viperport isn't a viper-racing-port ELF")
        return 1
    if LINUX_DEST.exists():
        shutil.rmtree(LINUX_DEST)
    for rel, data in sorted(files.items()):
        out = LINUX_DEST / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        if rel in LINUX_EXEC:
            out.chmod(out.stat().st_mode | 0o111)
    linux = (f"{LINUX_HEAD} viper-racing-port's native Linux standalone (v1.0's race.exe only), in linux/:\n"
             "viperport (32-bit ELF), its launcher viperport.sh, SDL2 (lib/libSDL2-2.0.so.0, zlib licence),\n"
             "README-linux.txt and LICENSES/.\n"
             f"from {tarball.name} (sha256 {tar_sha})\n"
             f"viper-racing-port linux commit {commit} ({date})\n"
             + "".join(f"sha256 {hashlib.sha256(files[r]).hexdigest()}  linux/{r}\n" for r in sorted(files)))
    _write_source(_halves()[0], linux)
    print(f"bundled viper-racing-port {commit} ({date}, Linux) into {LINUX_DEST.relative_to(ROOT)}: "
          f"{', '.join(sorted(files))}")
    print("in git, keep the executable bits: git update-index --chmod=+x "
          + " ".join(f"vrmod/assets/modern_engine/linux/{n}" for n in LINUX_EXEC))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("port", nargs="?", type=Path, help="the viper-racing-port checkout (Windows files)")
    ap.add_argument("--linux", type=Path, metavar="TARBALL", help="refresh the Linux files from this release tarball")
    args = ap.parse_args()
    if args.linux is not None:
        rc = update_linux(args.linux)
        if rc or args.port is None:
            return rc
    return update_windows(args.port or ROOT.parent / "viper-racing-port")


if __name__ == "__main__":
    sys.exit(main())
