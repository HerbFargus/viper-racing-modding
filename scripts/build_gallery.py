"""Package the canonical vrmod/ into gallery/vrmod.zip for the client-side gallery.

The gallery loads vrmod at runtime via Pyodide (pyodide.unpackArchive), so it
needs the package as a zip with vrmod/ at the top level. This is a BUILD ARTIFACT
-- it is gitignored and regenerated from the one source of truth (vrmod/) rather
than committed, so the gallery can never drift from the toolkit.

    python scripts/build_gallery.py
"""
from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "vrmod"
OUT = ROOT / "gallery" / "vrmod.zip"


def main() -> None:
    if not SRC.is_dir():
        raise SystemExit(f"vrmod package not found at {SRC}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(SRC.rglob("*")):
            if "__pycache__" in p.parts or p.suffix == ".pyc":
                continue
            if p.is_file():
                z.write(p, p.relative_to(ROOT).as_posix())   # -> vrmod/...
                n += 1
    print(f"wrote {OUT.relative_to(ROOT)} — {n} files, {OUT.stat().st_size/1e6:.2f} MB")


if __name__ == "__main__":
    main()
