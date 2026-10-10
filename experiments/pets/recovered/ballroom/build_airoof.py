"""AIRoof: does the AI avoid a solid that is over the track but high above it?

The same white room and loop, no balls. One flat .sol slab 7-8 m up, 100 m long and
26 m wide, spans the whole far straight (y = +55, road y 46..64) -- directly over both
AI racing lines. If the AI ignores a solid's height it will swerve or brake for it,
which rules out a collision roof over a racing track (a dome). Drawn grey so you can
see it. Built with build_overlap's ceiling code, pointed at the straight.
"""
import build_overlap as O

O.CEIL_X, O.CEIL_Y, O.CEIL_Z, O.CEIL_T = (-60.0, 40.0), (42.0, 68.0), 7.0, 1.0
NAME = "AIRoof"

if __name__ == "__main__":
    B = O.B
    B.make_base()
    B.write_count([], [], NAME)
    trk = B.HERE / f"{NAME}.trk"
    n = O.add_ceiling_solid(trk)
    out = B.DATA / f"{NAME}.tra"
    O.track.export_tra(trk, out, layout="flat")
    print(f"{out.name}: {n} solids, roof over the far straight, {out.stat().st_size:,} bytes")
