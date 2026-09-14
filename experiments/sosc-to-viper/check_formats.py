"""Checks for the two Streets of SimCity formats this experiment reads.

Both checks are the same shape, and it is the shape that has caught every
silent misread in this project: walk the whole file and require the walk to end
exactly where the file says it should. A per-item check passes happily while
the cursor drifts; a count or an end-offset does not.

  .MAX FACE records    The record's `size` field covers the WHOLE record, tag
                       and length included, and a face's vertex indices are a
                       contiguous block FOLLOWED by its UVs, not interleaved
                       with them. Both readings give 51 bytes for a triangle,
                       so the size alone does not tell you which -- reading
                       them interleaved yields indices like 49438 into a
                       285-vertex mesh. Requiring every model to yield exactly
                       the face count its table entry declares, with every
                       index in range, separates them.

  SIM3D.BMP atlas      Each texture carries its own header -- width, height, a
                       third word, then a per-row offset table of `height`
                       u32s -- before its pixels. Assuming the images are
                       tight-packed loses 68,736 bytes across the file and
                       lands index 83 in the middle of a building. Walking it
                       with the per-image header ends exactly on the file size.

    python check_formats.py <sosc_extracted_dir>
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from max2obj import models, read_model  # noqa: E402

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def check_max(path: Path) -> None:
    blob = path.read_bytes()
    table = models(blob)

    # One entry in every geometry table is named for the FILE, not for a model,
    # and it is not geometry: its face and vertex counts are the totals for
    # everything else in the table. Confirmed exactly, with no slack, in all
    # three files (8,187 / 13,119 / 13,839 faces), which makes it the best
    # available oracle -- the table states the answer the walk has to reach.
    stem = path.stem.lower()
    rollup = {k: v for k, v in table.items() if k.lower() == stem}
    real = {k: v for k, v in table.items() if k.lower() != stem}
    for name, (_, n_faces, n_verts) in rollup.items():
        check(f"{path.name}: the {name!r} entry totals the rest of the table",
              n_faces == sum(v[1] for v in real.values())
              and n_verts == sum(v[2] for v in real.values()),
              f"{n_faces:,} faces / {n_verts:,} verts over {len(real)} models")

    short = []
    out_of_range = []
    faces_read = 0
    for name, (addr, n_faces, n_verts) in sorted(real.items()):
        verts, faces = read_model(blob, addr, n_faces, n_verts)
        faces_read += len(faces)
        if len(faces) != n_faces:
            short.append(f"{name} {len(faces)}/{n_faces}")
        if len(verts) != n_verts:
            short.append(f"{name} {len(verts)}/{n_verts} verts")
        for f in faces:
            if any(i >= n_verts for i in f["idx"]):
                out_of_range.append(f"{name} index {max(f['idx'])} of {n_verts}")
                break

    check(f"{path.name}: every model reads the face count its table declares",
          not short, "; ".join(short[:3]) or
          f"{len(real)} models, {faces_read:,} face records")
    check(f"{path.name}: every vertex index is in range",
          not out_of_range, "; ".join(out_of_range[:3]) or
          "no index past the model's vertex count")


def check_atlas(path: Path) -> None:
    b = path.read_bytes()
    count = struct.unpack_from("<I", b, 8)[0]
    rescount = struct.unpack_from("<I", b, 12)[0]
    cur = 16 + rescount * 3 * 4
    sizes = []
    for _ in range(count):
        w, h = struct.unpack_from("<II", b, cur)[:2]
        data = cur + 12 + h * 4          # the per-image header, incl. row table
        sizes.append((w, h))
        cur = data + w * h
    check(f"{path.name}: the atlas walk ends exactly on the file size",
          cur == len(b), f"ended at {cur:,}, file is {len(b):,}"
          if cur != len(b) else f"{count} textures, {len(b):,} bytes")
    check(f"{path.name}: every texture has a plausible size",
          all(0 < w <= 1024 and 0 < h <= 1024 for w, h in sizes),
          f"largest {max(sizes, key=lambda s: s[0] * s[1])}")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("check_formats.py <sosc_extracted_dir>")
    sosc = Path(sys.argv[1])
    geo = sorted((sosc / "GEO").glob("*.MAX"))
    skin = sosc / "BMP" / "SIM3D.BMP"
    if not geo:
        raise SystemExit(f"no .MAX files under {sosc / 'GEO'}")
    for path in geo:
        check_max(path)
    if skin.is_file():
        check_atlas(skin)
    else:
        print(f"  (no {skin}, skipping the atlas walk)")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
