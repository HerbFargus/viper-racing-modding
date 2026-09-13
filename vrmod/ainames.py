"""Rename the seven AI opponents.

The game ships 50 driver names in `english.lng` under
`AIDriverName:<Tier>:Driver<0-6>` -- seven for each of Easy, Intermediate,
Hard and Career1 through Career4, and a single one for Career5. Which set you
meet depends on the difficulty you picked, so putting your friends in the field
means writing the same seven names across every tier; that is what `apply` does.
Career5 has only Driver0 and takes the first name alone.

HOW THE WRITE WORKS is lng.set_values: the new name is appended to the end of
the file and the entry's offset repointed at it, so a name is not limited to the
length of the one it replaces. Without that the feature would be close to
useless -- the Easy tier is Dunne, Berg, Hall, Hecker, Hook, White and Hayes,
and "Berg" leaves four characters to play with.

LENGTH. The FILE has no limit, which is not the same as the game having none:
the menu and the in-race standings draw these into a fixed space and nothing
here knows how much. SOFT_MAX is the longest name MGI themselves shipped,
"Featherly" at 9, which is the only real evidence about what the UI was built to
fit. It is advisory -- `apply` writes whatever it is given and `too_long`
reports what exceeds it, so the caller can warn rather than refuse. Raise it
once someone has looked at a long name in game.

RESET restores the stock names from the table below rather than from a backup of
the whole file, deliberately. `english.lng` also holds the track display names
the switcher rewrites, so restoring the file wholesale would silently undo
those. Only the keys this module owns are touched.
"""
from __future__ import annotations

from pathlib import Path

from . import lng, writepaths

SLOTS = 7
KEY = "AIDriverName:{tier}:Driver{slot}"
LANG_FILE = "english.lng"

# The order the game itself uses, easiest first. Career5 is last and short.
TIERS = ("Easy", "Intermediate", "Hard",
         "Career1", "Career2", "Career3", "Career4", "Career5")

# What MGI shipped. Read out of a pristine v1.0 english.lng, so a reset does not
# depend on having kept a backup. A localised build would have its own names
# here and would be reset to the English ones -- reset() says so rather than
# pretending otherwise.
STOCK: dict[str, list[str]] = {
    "Easy": ["Dunne", "Berg", "Hall", "Hecker", "Hook", "White", "Hayes"],
    "Intermediate": ["Barwood", "Falstein", "Miller", "Blair", "Vik\xf6ren",
                     "Andrade", "McDonald"],
    "Hard": ["Perrotti", "Mickus", "Okabe", "Poplardo", "Blake", "Curcio",
             "Alekman"],
    "Career1": ["Valdez", "Tillin", "Freeman", "Pazour", "Ambrose", "Bahr",
                "Denny"],
    "Career2": ["Nussbaum", "Poss", "Ragus", "Ridley", "Mickus", "Ellis",
                "Ritchie"],
    "Career3": ["Sentell", "Khudari", "Levesque", "Wheeler", "Heath", "Muir",
                "Matson"],
    "Career4": ["Finkel", "Chaswick", "Heykants", "Featherly", "Miyamoto",
                "Gilberto", "Mbowi"],
    "Career5": ["Ralph"],
}

# The longest name MGI shipped. Advisory -- see the module docstring.
SOFT_MAX = max(len(n) for names in STOCK.values() for n in names)


def lang_file(data_dir: str | Path) -> Path:
    """english.lng, wherever this pressing keeps it.

    v1.0 and v1.1 lay their install out differently and the Config lookup has
    already been wrong in three places because of it, so this goes through
    writepaths rather than assuming a sibling.
    """
    data_dir = Path(data_dir)
    here = data_dir / LANG_FILE
    if here.is_file():
        return here
    for d in (data_dir.parent, *writepaths.config_dirs(data_dir)):
        cand = Path(d) / LANG_FILE
        if cand.is_file():
            return cand
    return here                       # report the obvious path in the error


def read_all(data_dir: str | Path) -> dict[str, list[str]]:
    """Every tier's names as the file currently holds them."""
    table = lng.read(lang_file(data_dir))
    out: dict[str, list[str]] = {}
    for tier in TIERS:
        names = []
        for slot in range(SLOTS):
            v = table.value(KEY.format(tier=tier, slot=slot))
            if v is None:
                break
            names.append(v)
        if names:
            out[tier] = names
    return out


def current(data_dir: str | Path) -> list[str | None]:
    """The seven slots as a single list, or None where the tiers disagree.

    `apply` writes one name to every tier, so agreement across tiers is what a
    slot being "set" looks like. Disagreement means stock, or someone edited one
    tier by hand -- either way there is no single name to show in one box, and
    saying None is honest where picking the first tier's would not be.
    """
    tiers = read_all(data_dir)
    out: list[str | None] = []
    for slot in range(SLOTS):
        seen = {names[slot] for names in tiers.values() if len(names) > slot}
        out.append(seen.pop() if len(seen) == 1 else None)
    return out


def is_stock(data_dir: str | Path) -> bool:
    """True when every tier still reads exactly as MGI shipped it."""
    return read_all(data_dir) == STOCK


def too_long(names) -> list[tuple[int, str]]:
    """[(slot, name)] for names past SOFT_MAX. Advisory, not a refusal."""
    return [(i, n) for i, n in enumerate(names)
            if n and len(n) > SOFT_MAX]


def apply(data_dir: str | Path, names) -> int:
    """Write up to seven names across every tier. Returns entries changed.

    A blank or None slot is LEFT ALONE rather than blanked, so filling in two
    boxes and leaving five empty gives two new drivers and five stock ones,
    which is what half-filling a form means.
    """
    names = list(names)
    if len(names) > SLOTS:
        raise ValueError(f"{len(names)} names for {SLOTS} slots")
    changes: dict[str, str] = {}
    for slot, name in enumerate(names):
        if name is None or not str(name).strip():
            continue
        name = str(name).strip()
        for tier in TIERS:
            if slot < len(STOCK.get(tier, [])):
                changes[KEY.format(tier=tier, slot=slot)] = name
    if not changes:
        return 0
    return lng.set_values(lang_file(data_dir), changes)


def reset(data_dir: str | Path) -> int:
    """Put MGI's names back. Returns entries changed.

    Only the AIDriverName keys are touched. The track display names the
    switcher writes live in this same file and are none of this module's
    business.
    """
    changes = {KEY.format(tier=tier, slot=slot): name
               for tier, names in STOCK.items()
               for slot, name in enumerate(names)}
    return lng.set_values(lang_file(data_dir), changes)
