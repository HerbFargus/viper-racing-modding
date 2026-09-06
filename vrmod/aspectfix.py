"""Give widescreen more world at the sides instead of a taller crop (Hor+).

WHAT THE GAME ACTUALLY DOES. The renderer is DirectDraw/Direct3D IM, and the
whole of its resolution handling lives in the `D3DVIEWPORT2` it hands to
`IDirect3DViewport2::SetViewport2` (vtable slot `0x44`). The builder is one
function -- `0x459640` on v1.2.5, `0x4590xx` on retail -- and it is short enough
to read in full:

    fild  dword [esp+0x18]         ; dwHeight
    mov   dword [esp+8],    0x2c   ; dwSize = 44  -> D3DVIEWPORT2
    mov   dword [esp+0x1c], -1.0   ; dvClipX
    fidiv dword [esp+0x14]         ; / dwWidth    -> r = height/width
    mov   dword [esp+0x24],  2.0   ; dvClipWidth
    mov   dword [esp+0x2c],  0.0   ; dvMinZ
    mov   dword [esp+0x30],  1.0   ; dvMaxZ
    fst   dword [esp+0x20]         ; dvClipY      = r
    fmul  dword [2.0]
    ...                            ; two pushes shift esp by 8
    fstp  dword [esp+0x30]         ; dvClipHeight = 2r
    call  dword [eax+0x44]         ; SetViewport2

So the clip window is

    dvClipX = -1.0   dvClipWidth  = 2.0        <- both hard-coded immediates
    dvClipY =  r     dvClipHeight = 2r         <- r = dwHeight/dwWidth

and the projection matrix -- confirmed by logging every `SetTransform` during a
race -- is a per-camera CONSTANT with `_11 == _22` and `_31 == 0`: `1.274141`
for the race camera, `1.400415` for the menus, unchanged by resolution. All
aspect handling is here and nowhere else.

Two consequences follow, and both matter:

* The pipeline is horizontally SYMMETRIC at every stage. `dvClipX` is exactly
  `-dvClipWidth/2`, `_31` is zero in both the view and projection matrices.
  Nothing in the transform chain can shift the scene sideways.
* `dvClipWidth/dvClipHeight` is `1/r` = `dwWidth/dwHeight`, so pixels are square
  at any resolution, the HORIZONTAL field of view is fixed by the constant
  `dvClipWidth = 2.0`, and it is the VERTICAL field that shrinks as the screen
  gets wider. Stock widescreen is textbook Vert-: 1920x1080 shows exactly as
  much left-to-right as 640x480 did, and less top-to-bottom.

    640x480    -> viewport 640x416, r = 0.65      <- what the game was designed around
    1920x1080  -> viewport 1920x1016, r = 0.529   <- 19% less vertical field

THE FIX. Keep the original vertical field and widen the clip window to match the
screen, which is Hor+:

    R = max(R0, r)                               <- R0 = 0.65, the original
    dvClipY = R     dvClipHeight = 2R
    dvClipX = -R/r  dvClipWidth  = 2R/r          <- widened to the real aspect

`dvClipWidth/dvClipHeight` is still exactly `1/r`, so pixels stay square at every
resolution -- the patch only ever moves the clip window's SIZE, never its shape
or its centre.

The `max` matters, and clamping this way rather than pinning is what makes the
patch safe. This builder serves every viewport the game sets, not just the race
camera, and the rear-view mirror is a narrow one -- `167x129`, `r = 0.77`. Pinning
R to 0.65 would zoom the mirrors in by 19% at EVERY resolution, 640x480 included.
With the clamp, any viewport at least as tall as the design aspect keeps `R = r`
and comes out byte-identical to stock, so:

    640x480    viewport 640x416,  r = 0.65  -> R = r, every field stock: a no-op
    mirrors    viewport 167x129,  r = 0.77  -> R = r, untouched
    1920x1080  viewport 1920x1016,r = 0.53  -> R = 0.65, 23% more world sideways

Being a provable no-op at the original resolution is the property worth having:
the patch cannot regress framing it was not meant to touch.

    fidiv dword [esp+0x14]         ; r
    fld   st(0)                    ; keep a copy of r
    fld   dword [R0]
    fcom  st(1) / fstsw ax / sahf  ; R = max(R0, r)
    jbe/fstp                       ;   (fstp st(1) keeps R0, fstp st(0) keeps r)
    fst   dword [esp+0x20]         ; dvClipY = R
    fadd  st(0), st(0)             ; 2R
    fdiv  st(0), st(1)             ; 2R/r
    fstp  st(1)                    ; drop the spare r
    fst   dword [esp+0x24]         ; dvClipWidth
    fmul  dword [-0.5]
    fstp  dword [esp+0x1c]         ; dvClipX = -R/r
    mov   dword [esp+0x30], 1.0    ; dvMaxZ  (unchanged)
    fld   dword [esp+0x20]         ; R
    fadd  st(0), st(0)             ; 2R, left for the trailing fstp -> dvClipHeight

The x87 stack stays balanced exactly as the original did: `fild` pushes, the
trailing `fstp` past the two pushes pops. `fstsw` clobbers eax, which is dead
here -- the next reader reloads it from `[edx]`. The original's
`mov [esp+0x2c], 0` for dvMinZ is dropped rather than kept: the function's
opening `rep stosd` already zeroed all 44 bytes, so that store was redundant,
and the eight bytes it frees are what the comparison costs.

WHY THE EARLIER VERSION OF THIS PATCH WAS WRONG. It replaced the computed `r`
with the constant 0.65 and left `dvClipX`/`dvClipWidth` at their hard-coded
-1.0/2.0. That fixes `dvClipHeight` at 1.3 while the pixel viewport is 1.89:1,
so the clip window no longer matches the surface and the image is STRETCHED
horizontally by 23% instead of showing more world. Everything grows wider and
anything away from the middle is pushed further out -- which looks like the view
drifting off-centre, but is not: it is a stretch about a centre that never
moved. It also zoomed the mirrors, for the reason the `max` above now avoids.
Restore `race.bin.aspect-backup` before applying this version.

WHAT THIS DOES NOT DO. The 3D camera only. The HUD is drawn in screen space from
a 640x480-era layout and still does not scale (see the reference, HUD section).

Everything is located by PATTERN and the two constants are found by VALUE in
.rdata, so this works on retail 1.1 and community v1.2.5 alike -- the 66-byte
region is byte-identical between them apart from three operands.
"""
from __future__ import annotations

import re
import shutil
import struct
from pathlib import Path

RACE_BIN = "race.bin"

# The vertical half-field the ORIGINAL race view has. Not the screen's 0.75 --
# the 3D viewport is not the whole screen: the HUD banner takes the top 64 rows,
# so at 640x480 the game sets a viewport of 640x416 and r comes out at 0.65.
# Confirmed from the game's own logged viewports: `vp: 0 64 640 416` at 640x480
# and `vp: 0 64 1920 1016` at 1920x1080.
RATIO_ORIGINAL = 416 / 640          # 0.65

# The 66 bytes from `mov [esp+0x1c],-1.0` through `fmul [2.0]`. Wildcarded at
# the three build-specific operands: the FPU-present flag, the software-divide
# helper's rel32, and the address of the 2.0 constant.
_SITE = re.compile(
    rb"\xc7\x44\x24\x1c\x00\x00\x80\xbf"        # mov  [esp+0x1c], -1.0
    rb"\x83\x3d(....)\x00\x75\x06"              # cmp  [flag],0 / jne
    rb"\xda\x74\x24\x14\xeb\x09"                # fidiv [esp+0x14] / jmp
    rb"\xff\x74\x24\x14\xe8(....)"              # push [esp+0x14] / call helper
    rb"\xc7\x44\x24\x24\x00\x00\x00\x40"        # mov  [esp+0x24], 2.0
    rb"\xc7\x44\x24\x2c\x00\x00\x00\x00"        # mov  [esp+0x2c], 0.0
    rb"\xc7\x44\x24\x30\x00\x00\x80\x3f"        # mov  [esp+0x30], 1.0
    rb"\xd9\x54\x24\x20"                        # fst  [esp+0x20]
    rb"\xd8\x0d(....)",                         # fmul [2.0]
    re.S)
_REGION = 0x42                     # 66 bytes

# the same region once patched by this module
_FIXED = re.compile(
    rb"\xda\x74\x24\x14"                        # fidiv [esp+0x14]
    rb"\xd9\xc0\xd9\x05(....)"                  # fld st(0) / fld [R0]
    rb"\xd8\xd1\xdf\xe0\x9e\x76\x04"            # fcom st(1) / fstsw ax / sahf / jbe
    rb"\xdd\xd9\xeb\x02\xdd\xd8"                # fstp st(1) / jmp / fstp st(0)
    rb"\xd9\x54\x24\x20\xd8\xc0\xd8\xf1\xdd\xd9"  # dvClipY / 2R / 2R/r / drop
    rb"\xd9\x54\x24\x24\xd8\x0d(....)"          # fst [esp+0x24] / fmul [-0.5]
    rb"\xd9\x5c\x24\x1c",                       # fstp [esp+0x1c]
    re.S)

# the region as the FIRST, broken version of this patch left it
_OLD = re.compile(rb"\xdd\xd8\xd9\x05(....)\x90{16}", re.S)

UNPATCHED, PATCHED, OLD, UNKNOWN, MISSING = (
    "unpatched", "patched", "old-patch", "unknown", "missing")


class AspectError(RuntimeError):
    """The viewport builder can't be found, or isn't in a state we recognise."""


def _race_bin(data_dir: str | Path) -> Path:
    f = Path(data_dir) / RACE_BIN
    if not f.is_file():
        raise AspectError(f"no {RACE_BIN} in {data_dir}")
    return f


def _sections(blob: bytes):
    pe = struct.unpack_from("<I", blob, 0x3C)[0]
    nsec = struct.unpack_from("<H", blob, pe + 6)[0]
    optsz = struct.unpack_from("<H", blob, pe + 20)[0]
    base = struct.unpack_from("<I", blob, pe + 24 + 28)[0]
    off = pe + 24 + optsz
    out = []
    for i in range(nsec):
        s = blob[off + i * 40: off + (i + 1) * 40]
        name = s[:8].rstrip(b"\x00").decode("ascii", "replace")
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", s, 8)
        out.append((name, base + vaddr, vsize, rawptr, rawsize))
    return out


def _find_constant(blob: bytearray, value: float) -> int:
    """VA of an aligned float equal to `value` in .rdata.

    Found by value rather than by address so the same code works on builds that
    lay their constant pools out differently. A value the pool does not already
    hold is written into .rdata's slack -- the bytes between the section's
    virtual size and its larger raw size, which the loader maps because the raw
    size already equals the section-aligned virtual size. That space is zero in
    both builds and belongs to no data.
    """
    want = struct.pack("<f", value)
    for name, va, vsize, rawptr, rawsize in _sections(blob):
        if name != ".rdata":
            continue
        pool_end = rawptr + min(rawsize, vsize)
        for off in range(rawptr, pool_end - 4, 4):
            if blob[off:off + 4] == want:
                return va + (off - rawptr)
        slack, end = (rawptr + vsize + 3) & ~3, rawptr + rawsize
        for off in range(slack, end - 4, 4):
            if blob[off:off + 4] == want:            # already placed by us
                return va + (off - rawptr)
            if not any(blob[off:off + 4]):           # first free slot
                blob[off:off + 4] = want
                return va + (off - rawptr)
        raise AspectError("no free .rdata slack to hold the constant")
    raise AspectError("no .rdata section")


def _replacement(r0_va: int, half_va: int) -> bytes:
    """The 66 bytes that replace the region. `r0_va` holds R0, `half_va` -0.5."""
    out = (
        b"\xda\x74\x24\x14"                              # fidiv [esp+0x14]  -> r
        + b"\xd9\xc0"                                    # fld  st(0)        keep r
        + b"\xd9\x05" + struct.pack("<I", r0_va)         # fld  [R0]
        + b"\xd8\xd1"                                    # fcom st(1)
        + b"\xdf\xe0"                                    # fstsw ax
        + b"\x9e"                                        # sahf
        + b"\x76\x04"                                    # jbe  keep_r
        + b"\xdd\xd9"                                    # fstp st(1)        keep R0
        + b"\xeb\x02"                                    # jmp  done
        + b"\xdd\xd8"                                    # keep_r: fstp st(0)
        + b"\xd9\x54\x24\x20"                            # fst  [esp+0x20]  dvClipY = R
        + b"\xd8\xc0"                                    # fadd st(0), st(0)  -> 2R
        + b"\xd8\xf1"                                    # fdiv st(0), st(1)  -> 2R/r
        + b"\xdd\xd9"                                    # fstp st(1)        drop spare r
        + b"\xd9\x54\x24\x24"                            # fst  [esp+0x24]  dvClipWidth
        + b"\xd8\x0d" + struct.pack("<I", half_va)       # fmul [-0.5]
        + b"\xd9\x5c\x24\x1c"                            # fstp [esp+0x1c]  dvClipX
        + b"\xc7\x44\x24\x30\x00\x00\x80\x3f"            # mov  [esp+0x30], 1.0  dvMaxZ
        + b"\xd9\x44\x24\x20"                            # fld  [esp+0x20]  -> R
        + b"\xd8\xc0"                                    # fadd st(0), st(0)  -> 2R
    )                                                    # trailing fstp -> dvClipHeight
    if len(out) > _REGION:
        raise AspectError("internal error: replacement is too long")
    return out + b"\x90" * (_REGION - len(out))


def status(data_dir: str | Path) -> str:
    f = Path(data_dir) / RACE_BIN
    if not f.is_file():
        return MISSING
    blob = f.read_bytes()
    if len(_SITE.findall(blob)) == 1:
        return UNPATCHED
    if len(_FIXED.findall(blob)) == 1:
        return PATCHED
    if _OLD.search(blob):
        return OLD
    return UNKNOWN


def apply(data_dir: str | Path, ratio: float = RATIO_ORIGINAL) -> tuple[int, int, int]:
    """Widen the clip window to the screen's aspect. Returns (offset, R0 VA, -0.5 VA).

    The default 0.65 keeps the ORIGINAL vertical field wherever the viewport is
    wider than 640x416 and leaves every narrower viewport exactly as it was. A
    smaller value shows more vertically, at the cost of a narrower view.
    """
    f = _race_bin(data_dir)
    blob = bytearray(f.read_bytes())
    hits = list(_SITE.finditer(bytes(blob)))
    if len(hits) != 1:
        st = status(data_dir)
        if st == PATCHED:
            raise AspectError("already patched -- nothing to do")
        if st == OLD:
            raise AspectError(
                "this race.bin carries the earlier, broken aspect patch, which "
                "overwrote the operands this one needs. Restore "
                "race.bin.aspect-backup first.")
        raise AspectError(
            f"expected exactly one viewport builder, found {len(hits)}. "
            "This race.bin is not a build this patch understands.")

    r0_va = _find_constant(blob, ratio)           # may write into .rdata slack
    half_va = _find_constant(blob, -0.5)
    at = hits[0].start()
    blob[at:at + _REGION] = _replacement(r0_va, half_va)

    backup = f.with_suffix(f.suffix + ".aspect-backup")
    if not backup.exists():
        shutil.copy2(f, backup)
    f.write_bytes(bytes(blob))
    return at, r0_va, half_va
