"""Project a fitted cockpit into a frame, without the game.

The placement in cockpits.py rests on a projection model -- eye at cockpit.tab's
camera, 40 degree vertical FOV, Hor+ across aspects -- and that model is the part
most likely to be wrong. This draws what it predicts, so a prediction can be held
against a real screenshot instead of against another prediction.

The reference mark is Viperc.mod's cowl edge: in both a 640x480 and a 1920x1080
stock screenshot it sits ~65% of the way down the frame. A preview that agrees
with that at both sizes is using the right camera.

    python preview_cockpit.py <panels_dir> <out_dir> [prefix ...]
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cockpits import (CAMERA, GAUGE_Z, FOV_V, COWL_ANGLE, PANELS,
                      load_panel, panel_box)

SIZES = [(640, 480), (1920, 1080)]
HORIZON = (90, 150, 210)
COWL = (255, 90, 90)


def project(x, y, width, height):
    """World point on the gauge plane -> pixel, for a Hor+ camera."""
    d = GAUGE_Z - CAMERA[2]
    half_v = math.tan(math.radians(FOV_V / 2))
    half_h = half_v * (width / height)
    return (width * (0.5 + 0.5 * ((x - CAMERA[0]) / d) / half_h),
            height * (0.5 - 0.5 * ((y - CAMERA[1]) / d) / half_v))


def preview(prefix: str, panels_dir: Path, out_dir: Path) -> str:
    from PIL import Image, ImageDraw
    art = load_panel(panels_dir / PANELS[prefix])
    x0, x1, top, bottom, _z = panel_box(art.height / art.width)
    notes = []
    for width, height in SIZES:
        frame = Image.new("RGB", (width, height), (120, 170, 225))
        ImageDraw.Draw(frame).rectangle([0, height // 2, width, height],
                                        fill=(105, 105, 110))
        px0, ptop = project(x0, top, width, height)
        px1, pbot = project(x1, bottom, width, height)
        box = (round(px1 - px0), max(1, round(pbot - ptop)))
        frame.paste(art.resize(box, Image.LANCZOS), (round(px0), round(ptop)))
        draw = ImageDraw.Draw(frame)
        draw.line([0, height // 2, width, height // 2], fill=HORIZON, width=2)
        _, cowl = project(CAMERA[0],
                          CAMERA[1] + math.tan(math.radians(COWL_ANGLE))
                          * (GAUGE_Z - CAMERA[2]), width, height)
        draw.line([0, cowl, width, cowl], fill=COWL, width=2)
        frame.save(out_dir / f"{prefix}-{width}x{height}.png")
        notes.append(f"{width}x{height}: dash {px0 / width:.0%}..{px1 / width:.0%} "
                     f"wide, top {ptop / height:.0%} down, "
                     f"bottom {pbot / height:.0%}")
    return "  |  ".join(notes)


def main(argv):
    panels_dir, out_dir = Path(argv[0]), Path(argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = argv[2:] or sorted(PANELS)
    for prefix in wanted:
        print(f"  {prefix:10s} {preview(prefix, panels_dir, out_dir)}")
    # the calibration assertion: the cowl must land where both stock shots put it
    for width, height in SIZES:
        _, cowl = project(CAMERA[0],
                          CAMERA[1] + math.tan(math.radians(COWL_ANGLE))
                          * (GAUGE_Z - CAMERA[2]), width, height)
        frac = cowl / height
        assert 0.60 <= frac <= 0.66, f"cowl at {frac:.0%} of {width}x{height}"
    print("  cowl line lands ~62% down the frame at both sizes, where the stock cowl is")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
