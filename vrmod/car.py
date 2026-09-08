"""
Car assembly -- combine a .car archive's separate exterior part .mod files (body,
wheels, sub-parts) into one positioned scene, using .cf's dimension fields to place
the 4 wheel copies.

Naming convention (confirmed against the real viper.car and the community
car-creation tutorial): a car's parts all share one prefix, e.g. "viper":
    <prefix>0.mod            body, full detail (LOD0)
    <prefix>w.mod             STEERING wheel, not a tire -- see WHEELS below, this
                               tripped us up initially and is NOT what gets placed
                               at the 4 corners
    <prefix>b.mod, <prefix>s.mod   optional exterior sub-parts (mirror, rear spoiler --
                               not every car has both)
    <prefix>c.mod, Needle.mod   dashboard/gauge cluster and its speedometer needle --
                               EXCLUDED from assembly here; see COCKPIT PIECES below
    <prefix>.cf                stats/physics config

COCKPIT PIECES (<prefix>c.mod, Needle.mod) are deliberately left out. <prefix>c.mod's
own geometry reaches well above the body's actual roofline in body-space coordinates
(confirmed: body max Y 1.10, dashboard mesh max Y 1.27) despite being a real, correctly
-identified dashboard/gauge cluster (its textures are genuine gauge graphics, not a
misidentification, and they're plain opaque -- not a colorkey-transparency case either).
The game has a cockpit/interior camera view, so these are almost certainly authored
relative to that separate interior camera's own reference frame, not the exterior
body's world space -- a fundamentally different rendering context, not a wrong offset
to dial in. A proper interior view would be a separate viewer mode entirely (camera
parked at the driver's eye point), not a sub-part of this merged exterior mesh.

WHEELS (the tires, i.e. what actually goes at the 4 corners): NOT part of the car's
own .car archive at all, and NOT <prefix>w.mod -- that name is the steering wheel
(confirmed by decoding VIPERW.tex directly: it's unmistakably a Dodge steering wheel
with the snake-head hub badge, not a tire). Wasted a round of positioning effort
treating it as one before catching this. The real tire/rim meshes are shared, generic
assets living in race.res: wheel_1/2/3.mod (rear) and fwheel_1/2/3.mod (front),
textured with wheels.tex (also in race.res -- confirmed by decoding it: multiple rim
designs plus a tread pattern, unambiguously a tire texture). We use the "_1" variant
(moderate detail, single material) for both; "_2" is a much lower-poly LOD-looking
variant and "_3" carries an extra XRAY.tex material block whose purpose isn't
confirmed (possibly damage-state visualization), so it's avoided for now. Unlike the
steering wheel quad, these meshes are already correctly oriented (their own Y/Z span
the ~0.66m wheel diameter, X is the thin axle direction), so no rotation is needed --
only translation, with each wheel's own bounding box used to compute exactly how far
up to shift it so it sits flush on the ground rather than guessing a radius.

WHEEL POSITIONING (X/Z) is not stored anywhere in the mesh files. Investigated and
ruled out: Viper0.mod's body shell has no real geometric wheel-arch cutouts (checked
via boundary-edge topology -- the wheel wells are almost certainly just painted into
the texture). The game's damage model visibly moves wheels when the suspension
breaks, which means position has to be computed from suspension state at runtime,
not baked into a static mesh -- consistent with deriving it from .cf here:

    X (left/right): +-ftrack/2 for the front pair, +-rtrack/2 for the rear pair.
                     Well-justified -- these are literally "front/rear track width"
                     and match real Dodge Viper GTS specs.
    Z (front/rear along the car): +-wheelbase/2, CENTERED on the body's own Z=0 by
                     default. This is the one genuinely uncertain piece -- nothing
                     in the files pins down where the body's origin sits relative to
                     the axle line. Exposed as `z_offset` here so it can be tuned by
                     eye against a real reference screenshot.
    Y (ride height): computed directly from the real wheel_1.mod/fwheel_1.mod
                     geometry's own bounding box (shift up so its lowest point sits
                     at y=0), overridable via `wheel_radius`. (An earlier version of
                     this derived Y from a matching .tir file's section-width/aspect/
                     rim-diameter formula, back when the wheel part was still wrongly
                     the flat steering-wheel quad -- dropped now that real wheel
                     geometry with its own real scale is used instead.)

All of this -- especially Z -- is a starting assumption, not a confirmed fact.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import archive, cf, cockpit_tab, envelope, mod

INCH_TO_M = 0.0254

# Several materials a car's .mod files reference (e.g. UCAR.tex, EFFECTS.tex, WHEELS.tex)
# aren't in the car's own .car archive -- they're shared across cars and live in these
# resource archives instead. Searched in this order, alongside the car's own archive.
DEFAULT_SHARED_ARCHIVES = ["race.res", "common.res", "postrace.res", "paintkit.res", "ui.res"]


@dataclass
class CarAssembly:
    mesh: mod.Mesh
    stats: dict[str, float]
    prefix: str
    parts_found: dict[str, str] = field(default_factory=dict)  # role -> filename used
    cockpit_records: dict[str, tuple[float, ...]] = field(default_factory=dict)  # from cockpit.tab, cockpit assemblies only


def _entry_bytes(entries: list[archive.ArchiveEntry], name: str) -> bytes | None:
    for e in entries:
        if e.name.lower() == name.lower():
            return envelope.build(e.tag, e.version, e.payload)
    return None


def _find_prefix(entries: list[archive.ArchiveEntry]) -> str:
    for e in entries:
        m = re.match(r"^(.+)0\.mod$", e.name, re.IGNORECASE)
        if m:
            return m.group(1)
    raise ValueError("couldn't find a '<prefix>0.mod' body part to identify this car")


def find_in_shared_archives(data_dir: str | Path, name: str) -> bytes | None:
    """Look up `name` (e.g. a .mod or .tex filename) across DEFAULT_SHARED_ARCHIVES in
    `data_dir`, in order. Used both for a car's own wheel/texture lookups and standalone
    for shared, car-agnostic assets like ball.mod (the horn ball) that live in these
    archives without belonging to any particular car."""
    data_dir = Path(data_dir)
    for res_name in DEFAULT_SHARED_ARCHIVES:
        res_path = data_dir / res_name
        if not res_path.exists():
            continue
        raw = _entry_bytes(archive.read(res_path), name)
        if raw is not None:
            return raw
    return None


def find_shared(car_path: str | Path, entries: list[archive.ArchiveEntry], name: str) -> bytes | None:
    """Look up `name` in the car's own archive first, then each of
    DEFAULT_SHARED_ARCHIVES in turn (same directory as the car).

    This isn't just a fallback path -- shared assets like ball.mod (the horn ball)
    or spin_l.mod/spin_r.mod (wheel spindle caps) really do get per-car overrides in
    practice: stock viper.car has neither, but most of the Mario-Kart-character
    conversion mods in the community Data/ set (bowser.car, mario.car, etc.) ship
    their own ball.mod/ball.tex AND their own spin_l.mod/spin_r.mod, while every one
    of them still uses the shared arm_*.mod control-arm meshes. Any lookup for a
    part that might be one of these needs to check the car's own archive first, or
    it'll silently render the wrong (default/shared) part for a car that overrode
    it -- caught this exact bug in build_shell_html()'s horn ball tab, which used
    to call find_in_shared_archives() directly and skip the car's own archive."""
    raw = _entry_bytes(entries, name)
    if raw is not None:
        return raw
    return find_in_shared_archives(Path(car_path).parent, name)


def _ground_offset(wheel: mod.Mesh) -> float:
    """How far to shift a wheel mesh up so its lowest point touches y=0."""
    return -min(v.y for v in wheel.vertices)


def assemble_car(car_path: str | Path, z_offset: float = 0.0, wheel_radius: float | None = None) -> CarAssembly:
    car_path = Path(car_path)
    entries = archive.read(car_path)
    prefix = _find_prefix(entries)
    parts_found = {}

    body_bytes = _entry_bytes(entries, f"{prefix}0.mod")
    body = mod.parse(body_bytes)
    parts_found["body"] = f"{prefix}0.mod"
    all_parts = [body]

    # <prefix>c.mod and Needle.mod are interior/cockpit-view pieces (the dashboard/gauge
    # cluster and its speedometer needle) -- confirmed by decoding <prefix>c.mod's own
    # textures (real gauge graphics) and by its geometry reaching well above the body's
    # actual roofline in body-space coordinates. Almost certainly authored relative to a
    # separate interior camera's reference frame (the game has a cockpit view), not the
    # exterior body's world space, so they're excluded here rather than mis-positioned.
    for role, suffix in (("sub_b", "b"), ("sub_s", "s")):
        raw = _entry_bytes(entries, f"{prefix}{suffix}.mod")
        if raw is not None:
            all_parts.append(mod.parse(raw))
            parts_found[role] = f"{prefix}{suffix}.mod"

    cf_bytes = _entry_bytes(entries, f"{prefix}.cf")
    if cf_bytes is None:
        raise ValueError(f"no {prefix}.cf found -- can't compute wheel positions without it")
    stats = cf.parse(cf_bytes)
    parts_found["stats"] = f"{prefix}.cf"

    front_wheel_raw = find_shared(car_path, entries, "fwheel_1.mod")
    rear_wheel_raw = find_shared(car_path, entries, "wheel_1.mod")
    if front_wheel_raw is not None and rear_wheel_raw is not None:
        front_wheel = mod.parse(front_wheel_raw)
        rear_wheel = mod.parse(rear_wheel_raw)
        parts_found["wheel_front"] = "fwheel_1.mod"
        parts_found["wheel_rear"] = "wheel_1.mod"

        front_dy = wheel_radius if wheel_radius is not None else _ground_offset(front_wheel)
        rear_dy = wheel_radius if wheel_radius is not None else _ground_offset(rear_wheel)

        ftrack_m = stats["ftrack"] * INCH_TO_M
        rtrack_m = stats["rtrack"] * INCH_TO_M
        wheelbase_m = stats["wheelbase"] * INCH_TO_M
        front_z = wheelbase_m / 2 + z_offset
        rear_z = -wheelbase_m / 2 + z_offset

        corners = [
            (front_wheel, -ftrack_m / 2, front_dy, front_z, True),
            (front_wheel, ftrack_m / 2, front_dy, front_z, False),
            (rear_wheel, -rtrack_m / 2, rear_dy, rear_z, True),
            (rear_wheel, rtrack_m / 2, rear_dy, rear_z, False),
        ]
        for wheel, x, y, z, mirror in corners:
            all_parts.append(mod.transform(wheel, dx=x, dy=y, dz=z, mirror_x=mirror))

    combined = mod.merge(all_parts)
    return CarAssembly(mesh=combined, stats=stats, prefix=prefix, parts_found=parts_found)


@dataclass
class LiveCarAssembly:
    """Same body+wheel discovery as CarAssembly/assemble_car(), but the 4 wheel
    corners are kept separate from the chassis and from each other instead of being
    merged into one static mesh at one fixed X/Z. Each wheel mesh already has its Y
    (ground-touching height) and mirroring baked in via mod.transform() -- those
    don't depend on ftrack/rtrack/wheelbase -- but sits at local X=Z=0, so a caller
    can position it at runtime from whatever stat values it currently has (e.g. a
    live-editing UI recomputing position on every keystroke), rather than needing a
    fresh assemble_car() call per edit."""
    chassis: mod.Mesh
    # The 4 wheel corners come from the SHARED meshes in race.res, not the car.
    # They are None when those shared meshes aren't reachable (e.g. a community
    # car viewed without a race.res beside it) -- the body still renders, just
    # without wheels. Callers check `has_wheels` / parts_found before using them.
    front_wheel_left: mod.Mesh | None
    front_wheel_right: mod.Mesh | None
    rear_wheel_left: mod.Mesh | None
    rear_wheel_right: mod.Mesh | None
    stats: dict[str, float]
    prefix: str
    parts_found: dict[str, str] = field(default_factory=dict)

    @property
    def has_wheels(self) -> bool:
        return self.front_wheel_left is not None


def assemble_car_live(car_path: str | Path, wheel_radius: float | None = None) -> LiveCarAssembly:
    car_path = Path(car_path)
    entries = archive.read(car_path)
    prefix = _find_prefix(entries)
    parts_found = {}

    body_bytes = _entry_bytes(entries, f"{prefix}0.mod")
    body = mod.parse(body_bytes)
    parts_found["body"] = f"{prefix}0.mod"
    chassis_parts = [body]
    for role, suffix in (("sub_b", "b"), ("sub_s", "s")):
        raw = _entry_bytes(entries, f"{prefix}{suffix}.mod")
        if raw is not None:
            chassis_parts.append(mod.parse(raw))
            parts_found[role] = f"{prefix}{suffix}.mod"
    chassis = mod.merge(chassis_parts)

    cf_bytes = _entry_bytes(entries, f"{prefix}.cf")
    if cf_bytes is None:
        raise ValueError(f"no {prefix}.cf found -- can't compute wheel positions without it")
    stats = cf.parse(cf_bytes)
    parts_found["stats"] = f"{prefix}.cf"

    front_wheel_raw = find_shared(car_path, entries, "fwheel_1.mod")
    rear_wheel_raw = find_shared(car_path, entries, "wheel_1.mod")
    if front_wheel_raw is None or rear_wheel_raw is None:
        # The shared wheel meshes live in race.res, not this car. Without them
        # (a car viewed with no race.res beside it -- the community-gallery case)
        # render the body and its own parts wheel-less rather than failing.
        return LiveCarAssembly(
            chassis=chassis, front_wheel_left=None, front_wheel_right=None,
            rear_wheel_left=None, rear_wheel_right=None,
            stats=stats, prefix=prefix, parts_found=parts_found,
        )
    front_wheel = mod.parse(front_wheel_raw)
    rear_wheel = mod.parse(rear_wheel_raw)
    parts_found["wheel_front"] = "fwheel_1.mod"
    parts_found["wheel_rear"] = "wheel_1.mod"

    front_dy = wheel_radius if wheel_radius is not None else _ground_offset(front_wheel)
    rear_dy = wheel_radius if wheel_radius is not None else _ground_offset(rear_wheel)

    return LiveCarAssembly(
        chassis=chassis,
        front_wheel_left=mod.transform(front_wheel, dy=front_dy, mirror_x=True),
        front_wheel_right=mod.transform(front_wheel, dy=front_dy, mirror_x=False),
        rear_wheel_left=mod.transform(rear_wheel, dy=rear_dy, mirror_x=True),
        rear_wheel_right=mod.transform(rear_wheel, dy=rear_dy, mirror_x=False),
        stats=stats, prefix=prefix, parts_found=parts_found,
    )


def assemble_cockpit(car_path: str | Path) -> CarAssembly:
    """Dashboard + steering wheel, positioned for a cockpit-view render. Excluded from
    assemble_car() (see module docstring) since these live in a different reference
    frame than the exterior body; this builds them as their own small scene instead.

    Placement comes from <prefix>cockpit.tab (e.g. cockpit.tab in viper.car), a real
    data file we didn't open until directly asked "is there a stored setting for this,
    like the wheel's own camera.tab-style config?" -- there is. It's the same STAB
    format as the already-solved camera.tab (broadcast camera definitions), just
    car-side instead of track-side, with named records: "camera" (the cockpit-view eye
    position), "wheel" (the steering wheel's position), "rpm pt"/"mph pt" (3D pivot
    points for the tach/speedo needles -- confirms Needle.mod really is used as a 3D
    dash needle, not only the 2D HUD element also seen in the exterior view), and
    "rpm dat"/"mph dat" (needle rotation-angle ranges mapping to gauge values). This
    replaces an earlier version of this function that derived the wheel's position by
    guessing from the tach geometry and screenshot comparisons -- that approach got the
    depth direction backwards more than once before this file was found; the real data
    was sitting right there in the archive listing the whole time as "cockpit.tab".
    """
    car_path = Path(car_path)
    entries = archive.read(car_path)
    prefix = _find_prefix(entries)
    parts_found = {}

    dash_raw = _entry_bytes(entries, f"{prefix}c.mod")
    wheel_raw = _entry_bytes(entries, f"{prefix}w.mod")
    cockpit_tab_raw = _entry_bytes(entries, "cockpit.tab")
    if dash_raw is None or wheel_raw is None:
        raise ValueError(f"couldn't find {prefix}c.mod and/or {prefix}w.mod for a cockpit view")
    if cockpit_tab_raw is None:
        raise ValueError("couldn't find cockpit.tab -- no stored wheel/camera position for this car")
    dash = mod.parse(dash_raw)
    wheel = mod.parse(wheel_raw)
    parts_found["dash"] = f"{prefix}c.mod"
    parts_found["wheel"] = f"{prefix}w.mod"
    parts_found["cockpit_tab"] = "cockpit.tab"

    records = cockpit_tab.parse(cockpit_tab_raw)
    wx, wy, wz = records["wheel"]

    # No rotation needed -- the wheel's own orientation was confirmed correct as-is;
    # an earlier pass here wrongly "fixed" a camera-angle problem by flipping the mesh
    # 180 degrees, which was reverted once the real cause (camera, not mesh) was found.
    positioned_wheel = mod.transform(wheel, dx=wx, dy=wy, dz=wz)
    combined = mod.merge([dash, positioned_wheel])
    return CarAssembly(
        mesh=combined, stats={}, prefix=prefix, parts_found=parts_found, cockpit_records=records
    )


# The complete set of texture NAMES the stock shared archives (race.res etc.)
# provide -- filenames only, not the textures themselves. This is what lets the
# provenance diagnostic tell a "borrows a stock shared texture" reference (fine
# for anyone, since every install has these) apart from a "needs a file the
# author didn't ship" one, WITHOUT a copy of race.res present -- which is exactly
# the browser-gallery case. Captured from a stock v1.2.5 install; if a real set
# of shared archives is on hand, pass its names to texture_provenance() instead.
STOCK_SHARED_TEX = frozenset({
    "ucar.tex", "wheels.tex", "effects.tex", "effectsx.tex",
    "xray.tex", "damage.tex", "skid.tex", "splash.tex", "envmap.tex",
})


def body_prefix(entries: list[archive.ArchiveEntry]) -> str | None:
    """The car's filename prefix, read from its body mesh (<prefix>0.mod). This is
    also the name of its body-paint slot: <prefix>.tex (see texture_provenance)."""
    be = next((e for e in entries if e.name.lower().endswith("0.mod")), None)
    return be.name[:-5] if be else None


# The <prefix>1.tab spec sheet (STAB, tag "BATS") is a fixed-width key/value
# table: a header, then records of a 33-byte KEY field + a 33-byte VALUE field.
# Record 0 is "Name" -> the in-game display name. The value is a NUL-terminated
# string inside its 33-byte field, so a rename is a pure in-place field overwrite:
# the payload size and every other stat column stay put. (This is the display
# label only -- distinct from the car's FILENAME, which is its load-bearing
# identity; renaming the name here is safe, renaming the .car file is not.)
_TAB_FIELD = 33


def _spec_tab_entry(entries: list[archive.ArchiveEntry]):
    """The car's <prefix>1.tab spec sheet, if present."""
    prefix = body_prefix(entries)
    if prefix:
        want = f"{prefix}1.tab".lower()
        for e in entries:
            if e.name.lower() == want:
                return e
    for e in entries:   # fallback: any *1.tab that actually carries a Name field
        if e.name.lower().endswith("1.tab") and b"Name" in e.payload[:160]:
            return e
    return None


def read_car_name(entries: list[archive.ArchiveEntry]) -> str | None:
    """The car's in-game display name (record 0 'Name' in <prefix>1.tab)."""
    e = _spec_tab_entry(entries)
    if e is None:
        return None
    off = e.payload.find(b"Name")
    if off < 0:
        return None
    val = e.payload[off + _TAB_FIELD: off + 2 * _TAB_FIELD]
    return val.split(b"\x00", 1)[0].decode("latin-1").strip() or None


def set_car_name(entries: list[archive.ArchiveEntry], new_name: str) -> list[archive.ArchiveEntry]:
    """Return entries with the car's display name rewritten in place in its
    spec-sheet tab. Capped at 32 chars (the field is 33 wide, NUL-terminated);
    nothing else in the tab moves. Raises if there's no spec sheet / Name field.

    Note: the field STORES up to 32 chars, but the in-game car-select menu only
    DISPLAYS ~24 before truncating (confirmed in-game), so the toolkit's name
    inputs cap at 24. Longer names written here are valid, just clipped on screen."""
    e = _spec_tab_entry(entries)
    if e is None:
        raise ValueError("this car has no <prefix>1.tab spec sheet to rename")
    off = e.payload.find(b"Name")
    if off < 0:
        raise ValueError("no Name field in the car's spec sheet")
    field = new_name.strip().encode("latin-1", "replace")[: _TAB_FIELD - 1]
    pay = bytearray(e.payload)
    pay[off + _TAB_FIELD: off + 2 * _TAB_FIELD] = field.ljust(_TAB_FIELD, b"\x00")
    return archive.replace_entry(entries, e.name, envelope.build(e.tag, e.version, bytes(pay)))


# Shared, car-agnostic members whose FILENAME is fixed regardless of the car
# prefix (the game looks these up by these exact names). Their filenames are NOT
# re-prefixed by a fork; their internal material references still are (Needle.mod
# names the body paint slot). See the format reference, car naming.
_FIXED_MEMBERS = {"cockpit.tab", "needle.mod", "ball.mod", "horn.sfx",
                  "shift1.sfx", "squeal.sfx"}


def _reprefix(name: str, old: str, new: str) -> str:
    """Swap a leading `old` prefix for `new`, keeping the rest (and its case)."""
    return new + name[len(old):] if name.lower().startswith(old.lower()) else name


def fork_car(entries: list[archive.ArchiveEntry], new_prefix: str
             ) -> list[archive.ArchiveEntry]:
    """Clone a car under a NEW filename prefix, so it becomes a standalone
    vehicle distinct from the one it was forked from -- e.g. fork viper.car to
    jeep so you can drive jeep.car while the AI field stays viper.

    The game derives every `<prefix>*` member name it loads from the .car file's
    own on-disk name, so a car saved as `jeep.car` MUST contain `jeep0.mod`,
    `jeep.cf`, `jeepL.tab`, ... -- just renaming the file leaves it hunting for
    members that never existed (`ResourceGet("jeep0.mod") returning NULL!` ->
    `Couldn't load ModelInfo jeep0.mod`). This returns entries with:
      * every `<old>*` member renamed to `<new>*` (the shared, car-agnostic
        members keep their fixed names), and
      * every `.mod` material that references an `<old>`-prefixed texture (the
        paint slot `<old>.tex`, decals `<old>d*.tex`, wheel `<old>w.tex`)
        rewritten to the `<new>` prefix, so the mesh still finds its textures.

    Only names change; geometry, ranges, physics, tables and the display name
    (set separately via set_car_name) carry over unchanged. Caller writes the
    result as `<new_prefix>.car`."""
    old = body_prefix(entries)
    if not old:
        raise ValueError("couldn't determine this car's prefix")
    new = new_prefix.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+", new or ""):
        raise ValueError(f"invalid prefix {new_prefix!r} (use letters/digits/underscore)")
    if new.lower() == old.lower():
        raise ValueError(f"new prefix is already the current one ({old!r})")
    longest = max((len(e.name) - len(old) for e in entries
                   if e.name.lower().startswith(old.lower())), default=0)
    if len(new) + longest > 16:                       # archive name field is 16 bytes
        raise ValueError(f"prefix {new!r} too long -- member names would exceed 16 chars")

    # Only rewrite material references to textures actually SHIPPED (and thus
    # renamed) inside this .car -- the decals/wheel (<old>d*.tex, <old>w.tex).
    # The body PAINT slot <old>.tex is NOT shipped; it's supplied at runtime by
    # NAME from the paintkit, so a fork must keep referencing the base car's
    # paint (rewriting it to <new>.tex leaves the body untextured, since no
    # <new>.tex paint exists). Shared textures (UCAR/WHEELS/EFFECTS.tex) aren't
    # prefixed and are left alone automatically.
    renamed_tex = {e.name.lower() for e in entries
                   if e.name.lower().startswith(old.lower()) and e.name.lower().endswith(".tex")}
    mod_tag = getattr(mod, "TAG", b"FNIM")
    out: list[archive.ArchiveEntry] = []
    for e in entries:
        payload = e.payload
        if e.tag == mod_tag:
            std = envelope.build(e.tag, e.version, e.payload)
            for i, m in enumerate(mod.parse(std).materials):
                if m.name.lower() in renamed_tex:
                    std = mod.set_material_texture(std, i, _reprefix(m.name, old, new))
            payload = envelope.parse(std).payload
        name = e.name if e.name.lower() in _FIXED_MEMBERS else _reprefix(e.name, old, new)
        out.append(archive.ArchiveEntry(name=name, tag=e.tag,
                                        version=e.version, payload=payload))
    return out


# Default per-level vertex fractions of LOD0, for LOD1..LOD7 -- a gentle
# geometric falloff (lots of detail near, little far). Override with explicit
# targets. The stock cars pair levels (LOD0==LOD1 etc.); this is monotonic,
# which is simpler and fine for a generated chain.
_LOD_FRACS = (0.65, 0.45, 0.30, 0.20, 0.12, 0.07, 0.04)


def build_lod_chain(entries: list[archive.ArchiveEntry], *,
                    targets: list[int] | None = None, levels: int = 7,
                    keep_existing: bool = False
                    ) -> tuple[list[archive.ArchiveEntry], list[tuple[str, int]]]:
    """Generate a car's LOD chain `<prefix>1.mod`..`<prefix>N.mod` by decimating
    its body `<prefix>0.mod`, carrying the body's MATERIALS through so every level
    keeps the same textures (LOD0's shipped skin), independent of the runtime
    paint slot.

    This replaces two bad states: the old "copy LOD0 N times" hack (renders every
    level at full detail -> zero performance benefit) and the "leftover donor LODs"
    problem (a car forked from viper whose LOD1-7 are still viper meshes, so it
    reverts to a viper at any distance -- roster, replays, distant traffic).

    Returns (entries, made) where `made` is [(member, vertex_count), ...].

    targets       explicit per-level vertex counts (LOD1 first); default is a
                  geometric falloff of the body's vertex count (_LOD_FRACS).
    levels        how many LODs to generate (1..levels); default 7 (full chain).
    keep_existing don't overwrite a level that already exists -- so a hand-authored
                  LOD is preserved and only the missing ones are generated. The
                  generated meshes are ordinary `.mod` members, so any level can
                  still be exported/replaced/edited afterwards via the parts drawer,
                  moddecimate, modretex, or an OBJ round-trip.
    """
    prefix = body_prefix(entries)
    if not prefix:
        raise ValueError("couldn't determine this car's prefix")
    body = next((e for e in entries if e.name.lower() == f"{prefix.lower()}0.mod"), None)
    if body is None:
        raise ValueError(f"no body mesh {prefix}0.mod to build LODs from")
    body_mesh = mod.parse(envelope.build(body.tag, body.version, body.payload))
    V = len(body_mesh.vertices)
    if targets is None:
        targets = [max(12, int(round(V * f))) for f in _LOD_FRACS[:levels]]
    have = {e.name.lower() for e in entries}
    out = entries
    made: list[tuple[str, int]] = []
    # Decimate each level from LOD0 (best quality), but never let a level exceed
    # the previous one: on a low-poly/small-block mesh the decimator safely "backs
    # off" to the original rather than wiping a material's faces, which would break
    # monotonicity -- so reuse the previous (smaller) level whenever that happens.
    prev_mesh, prev_v = body_mesh, V
    for i in range(1, levels + 1):
        name = f"{prefix}{i}.mod"
        if keep_existing and name.lower() in have:
            continue
        tgt = targets[i - 1] if i - 1 < len(targets) else targets[-1]
        dec = mod.decimate(body_mesh, tgt)
        if len(dec.vertices) >= prev_v:          # backed off / not smaller than previous level
            dec = prev_mesh
        out = archive.upsert_entry(out, name, mod.build(dec, version=body.version))
        made.append((name, len(dec.vertices)))
        prev_mesh, prev_v = dec, len(dec.vertices)
    return out, made


def car_material_names(entries: list[archive.ArchiveEntry]) -> set[str]:
    """Every material name referenced by any of a car's .mod meshes."""
    names: set[str] = set()
    for e in entries:
        if not e.name.lower().endswith(".mod"):
            continue
        try:
            m = mod.parse(envelope.build(e.tag, e.version, e.payload))
        except Exception:
            continue
        names |= {mm.name for mm in m.materials if mm.name}
    return names


def texture_provenance(
    car_path: str | Path, shared_names: set[str] | frozenset[str] | None = None,
) -> dict:
    """Classify where every texture a car references comes from -- a portability
    diagnostic that needs no shared archives present.

    Each material name a mesh uses falls into one of four buckets:
      - own    : shipped inside this .car (renders anywhere, fully self-contained)
      - shared : a stock shared texture (ucar/wheels/effects/... -- fine for
                 anyone, since every install has these; renders grey without them)
      - paint  : the body-paint slot <prefix>.tex, not shipped -- remapped at
                 runtime to the player's Paint Kit (Config/paintN.tex); normal
      - missing: none of the above -- NOT in the car, NOT a stock shared name,
                 NOT the paint slot. The red flag: it depends on a file the author
                 didn't ship (typically their own modified race.res), so it will
                 render wrong for anyone who downloads it. "works on my machine".

    Returns {own, shared, paint, missing: sorted[str], prefix, verdict} where
    verdict is "self-contained" | "portable" | "incomplete".
    """
    entries = archive.read(Path(car_path))
    own = {e.name.lower() for e in entries if e.name.lower().endswith(".tex")}
    shared = {s.lower() for s in (shared_names if shared_names is not None else STOCK_SHARED_TEX)}
    prefix = body_prefix(entries)
    paint_name = f"{prefix}.tex".lower() if prefix else None

    buckets: dict[str, set[str]] = {"own": set(), "shared": set(), "paint": set(), "missing": set()}
    for name in car_material_names(entries):
        n = name.lower()
        if n in own:
            buckets["own"].add(name)
        elif n in shared:
            buckets["shared"].add(name)
        elif paint_name and n == paint_name:
            buckets["paint"].add(name)
        else:
            buckets["missing"].add(name)

    if buckets["missing"]:
        verdict = "incomplete"                         # needs files the author didn't ship
    elif not buckets["shared"] and not buckets["paint"]:
        verdict = "self-contained"                     # renders fully anywhere
    else:
        verdict = "portable"                           # only leans on stock/paint, which everyone has
    return {
        "prefix": prefix, "verdict": verdict,
        **{k: sorted(v) for k, v in buckets.items()},
    }


def resolve_textures(
    car_path: str | Path, material_names: set[str], shared_archives: list[str] | None = None,
    paint_texture: str | Path | None = None,
) -> dict[str, bytes | None]:
    """Find the raw .tex bytes for each of a set of material names, checking the car's
    own archive first, then a set of shared resource archives (in the same directory as
    the car) in order.

    The main body paint (material name "VIPER.tex"/"Viper.tex" on the retail Viper)
    genuinely isn't in any shipped archive -- it turns out that name is a placeholder
    the game remaps at runtime to whichever paintN.tex a player has selected via the
    in-game Paint Kit, which lives in a per-install Config/ folder (paint0.tex..
    paint8.tex), entirely separate from the static Data/ archives. `paint_texture` lets
    a caller point at one specific paintN.tex (or any .tex) to use for whatever couldn't
    be resolved from the archives -- there's no way to know which slot is "current"
    from static files alone. Still-unresolved names come back as None so callers can
    fall back to a flat color."""
    car_path = Path(car_path)
    lookup: dict[str, bytes] = {}

    def index_archive(path: Path) -> None:
        if not path.exists():
            return
        for e in archive.read(path):
            key = e.name.lower()
            if key not in lookup:
                lookup[key] = envelope.build(e.tag, e.version, e.payload)

    index_archive(car_path)
    for res_name in (shared_archives if shared_archives is not None else DEFAULT_SHARED_ARCHIVES):
        index_archive(car_path.parent / res_name)

    paint_bytes = Path(paint_texture).read_bytes() if paint_texture is not None else None
    return {name: lookup.get(name.lower(), paint_bytes) for name in material_names}
