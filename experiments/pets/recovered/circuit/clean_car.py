"""Make a built jeep shareable: nothing inside it that we lack the right to redistribute.

  cockpit     <prefix>c.mod, <prefix>w.mod, Needle.mod and cockpit.tab come from the donor
              van -- a Streets of SimCity conversion -- so they go. A car with no
              cockpit of its own uses the game's shared Viper cockpit (the AI field
              does exactly this), which is not shipped inside the car.
  sounds      <prefix>i/0/1/2.sfx were SoSC's VW-bus sample; replaced with synthesised
              engines (engine_sfx.py). The .ens crossfade config is kept: it is the
              stock Viper's, identical to Val's.
  horn        the generated boulder rumble (make_rumble.py)
  textures    every .tex no remaining mesh references is dropped (the van's old skins
              and dash art ride along otherwise)
  spec sheet  <prefix>1.tab rebuilt from Val's clean one (the van's was misaligned: its
              name started a byte early and blanked the 0-60 label), with this car's
              figures
  retexture   optional {name.tex: PIL image} replacing texture payloads by name

    clean(car_in, car_out, prefix=..., display=..., spec={...}, engine=(pulses, cylinders))
"""
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"C:\Users\seamus\Desktop\claude-code\viper-mod-manager")
sys.path.insert(0, str(HERE))
import engine_sfx  # noqa: E402
import make_rumble  # noqa: E402
from vrmod import archive, car, envelope, mod, sfx, tex  # noqa: E402

INSTALL = Path(r"C:\Users\seamus\Desktop\claude-code\game-files\installs\v1.0-RC")
VAL = INSTALL / "Backups" / "Viper.car.boulder-backup"
TAB_FIELD = 33
SPEC_LABELS = ("Name", "0-60", "0-100", "q time", "q speed", "top speed", "engine", "e size",
               "power max", "power rpm", "torque max", "torque rpm", "redline")


def spec_tab(prefix, values):
    """Val's <viper>1.tab with each labelled value rewritten in its own 33-byte field."""
    ve = next(e for e in archive.read(VAL) if e.name.lower().endswith("1.tab"))
    pay = bytearray(ve.payload)
    for label in SPEC_LABELS:
        if label not in values:
            continue
        key = label.encode().ljust(12, b" ")
        off = pay.find(key)
        if off < 0:
            raise ValueError(f"no {label!r} label in Val's spec sheet")
        field = str(values[label]).encode("latin-1")[:TAB_FIELD - 1]
        pay[off + TAB_FIELD: off + 2 * TAB_FIELD] = field.ljust(TAB_FIELD, b"\x00")
    return archive.ArchiveEntry(name=f"{prefix}1.tab", tag=ve.tag, version=ve.version, payload=bytes(pay))


def clean(car_in, car_out, *, prefix, display, spec, engine, retexture=None):
    data = Path(car_in).read_bytes()
    layout = archive.read_layout(data)
    entries = archive.read_bytes(data)
    drop = {f"{prefix}c.mod", f"{prefix}w.mod", "needle.mod", "cockpit.tab"}
    entries = [e for e in entries if e.name.lower() not in drop]

    rate, loops = engine_sfx.engine_set(*engine)
    for e in entries:
        n = e.name.lower()
        for suffix, samples in loops.items():
            if n == f"{prefix}{suffix}.sfx":
                info = sfx.SfxInfo(format_tag=1, channels=1, sample_rate=rate, byte_rate=rate * 2, block_align=2,
                                   bits_per_sample=16, sample_data=samples.tobytes())
                env = envelope.parse(sfx.build(info))
                e.tag, e.version, e.payload = env.tag, env.version, env.payload
    horn = envelope.parse(make_rumble.as_sfx(make_rumble.rumble()))
    for e in entries:
        if e.name.lower() == "horn.sfx":
            e.tag, e.version, e.payload = horn.tag, horn.version, horn.payload
            break
    else:
        entries.append(archive.ArchiveEntry(name="horn.sfx", tag=horn.tag, version=horn.version, payload=horn.payload))

    for name, img in (retexture or {}).items():
        a = np.array(img.convert("RGB")).astype(int)
        a[a.max(axis=2) < 10] = 10
        from PIL import Image
        t = envelope.parse(tex.encode_to_tex(Image.fromarray(a.astype(np.uint8)).tobytes(), img.width,
                                             mode="opaque", wrap=1))
        for e in entries:
            if e.name.lower() == name.lower():
                e.tag, e.version, e.payload = t.tag, t.version, t.payload

    used = set()
    for e in entries:
        if e.name.lower().endswith(".mod"):
            m = mod.parse(envelope.build(e.tag, e.version, e.payload))
            used |= {mt.name.lower() for mt in m.materials if mt.name}
    dead = [e.name for e in entries if e.name.lower().endswith(".tex") and e.name.lower() not in used]
    entries = [e for e in entries if e.name not in dead]

    entries = [e for e in entries if e.name.lower() != f"{prefix}1.tab"] + [spec_tab(prefix, dict(spec, Name=display))]
    Path(car_out).write_bytes(archive.to_bytes(entries, partitioned=layout.partitioned))
    prov = car.texture_provenance(car_out)
    from vrmod import catalog
    sheet = catalog.read_spec_tab(archive.read(car_out))
    return {"dropped": sorted(drop | {d.lower() for d in dead}), "provenance": prov["verdict"],
            "missing": prov["missing"], "own_textures": prov["own"], "spec": sheet,
            "members": len(entries)}
