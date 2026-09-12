"""Checks for reading community car packs.

Mostly synthetic: zips are built here, so the suite does not depend on the car
collection being present or in any particular state -- the mistake three other
suites in this repo have already made.

The .rar path needs 7-Zip and a real .rar, so those checks announce themselves
as skipped rather than passing quietly. A silent skip would be the worst
outcome: .rar is 1,480 of the 1,667 packs, and a reader that had quietly stopped
working on them would look perfectly healthy here.

    python scripts/check_carpack.py [a-real-pack.rar]
"""
from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import carpack  # noqa: E402

PASS = FAIL = 0

VAL_README = """Stock.car CONVERTED from my NFS4 game to VIPER RACING   Jan 10 2008 BY:

VAL IN MOOSE JAW , SASKATCHEWAN , CANADA.

e-mail.......val5662@yahoo.com

PERMISSION INFO:
 If you want to convert this car to any other game go ahead...
"""

FRANK_README = """Viper car

name: Ferrari 250 GTO (4 litre) 1962
filename: 250gto.car

imported from SCGT to Viper format by Frank P. Wolf

credits: Thanks fly to Kim for the SCGT car
contact: racingwolf@aol.com or support@monstergames.com
"""


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def make_zip(p: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(p, "w") as z:
        for n, b in files.items():
            z.writestr(n, b)
    return p


def main() -> int:
    print("parsing the readme templates\n")

    check("Val's BY: template gives the author",
          carpack.author_of(VAL_README) == "VAL IN MOOSE JAW , SASKATCHEWAN , CANADA",
          repr(carpack.author_of(VAL_README)))
    check("Frank's inline 'by' gives the author",
          carpack.author_of(FRANK_README) == "Frank P. Wolf",
          repr(carpack.author_of(FRANK_README)))
    check("a readme with neither gives no author, rather than a guess",
          carpack.author_of("just some text about a car") is None)
    check("'made by my friend Bob' strips the filler",
          carpack.author_of("made by my friend Bob") == "Bob",
          repr(carpack.author_of("made by my friend Bob")))
    check("'converted by me' is not treated as a name",
          carpack.author_of("converted by me") is None)

    check("Frank's 'name:' line gives the title",
          carpack.title_of(FRANK_README) == "Ferrari 250 GTO (4 litre) 1962",
          repr(carpack.title_of(FRANK_README)))
    check("no 'name:' line gives no title", carpack.title_of(VAL_README) is None)

    check("'my NFS4 game' normalises to the game",
          carpack.converted_from(VAL_README) == "NFS4",
          repr(carpack.converted_from(VAL_README)))
    check("'imported from SCGT to Viper' gives SCGT",
          carpack.converted_from(FRANK_README) == "SCGT")
    check("'one of my games' names nothing, so it stays blank",
          carpack.converted_from("CONVERTED from one of my games to VIPER") is None,
          repr(carpack.converted_from("CONVERTED from one of my games to VIPER")))
    check("the date is picked up", carpack.dated(VAL_README) == "Jan 10 2008",
          repr(carpack.dated(VAL_README)))

    print("\ncanonical author names\n")

    # Real strings out of the collection. Val signs 995 packs under eight
    # spellings; "an UNKNOWN AUTHOR" is a stock phrase in his template meaning
    # the opposite of an attribution, and was being counted as a person.
    for raw, want in (
            ("VAL IN MOOSE JAW , SASKATCHEWAN , CANADA", "Val"),
            ("Val in Moose Jaw, Sask., Canada", "Val"),
            ("Val in Moose Jaw", "Val"),
            ("Val", "Val"),
            ("Frank P. Wolf", "Frank P. Wolf"),
            ("F.P.Wolf", "Frank P. Wolf"),
            ("sucahyo", "Sucahyo"),
            ("an UNKNOWN  AUTHOR", None),
            ("Unknown Author", None),
            ("me from the game Motor City Online", None),
            ("Nitroracer", "Nitroracer"),
            ("Vic Edelbrock", "Vic Edelbrock"),
    ):
        got = carpack.canonical_author(raw)
        check(f"  {raw[:42]!r} -> {want!r}", got == want, repr(got))
    check("a name that is nobody's alias is left alone",
          carpack.canonical_author("Some Person") == "Some Person")
    check("None in, None out", carpack.canonical_author(None) is None)

    print("\nemail redaction\n")

    out, n = carpack.redact_emails(FRANK_README)
    check("every address is redacted by default", n == 2 and "@" not in out, f"{n} found")
    check("  the marker is left in place", "[email redacted]" in out)
    out, n = carpack.redact_emails(FRANK_README, keep_domains=("monstergames.com",))
    check("keep_domains keeps a company address",
          n == 1 and "support@monstergames.com" in out and "racingwolf" not in out,
          f"{n} redacted")
    check("text with no address is returned unchanged",
          carpack.redact_emails("nothing here") == ("nothing here", 0))

    print("\nreading a pack\n")

    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        z = make_zip(tmp / "0test.zip", {
            "0test.car": b"CARDATA" * 100,
            "0test.jpg": b"\xff\xd8JPEG",
            "0test.txt": VAL_README.encode(),
            "stub.txt": b"x",                       # smaller: must lose
        })
        info = carpack.describe(z, collection="valscars")
        check("members are listed", len(info.members) == 4, f"{len(info.members)}")
        check("the .car is identified", info.cars == ["0test.car"], str(info.cars))
        check("the image is identified", info.images == ["0test.jpg"])
        check("the BIGGEST readme wins, not the first",
              info.readme_name == "0test.txt", repr(info.readme_name))
        check("the author came through", info.author is not None)
        check("the address in the recorded readme is redacted",
              info.emails_redacted == 1 and "yahoo" not in (info.readme or ""))
        check("size and hash are of the archive itself",
              info.size == z.stat().st_size and len(info.sha256) == 64)
        check("collection is recorded", info.collection == "valscars")
        check("no error on a good pack", info.error is None)

        # A pack with no readme at all is normal, not an error.
        z2 = make_zip(tmp / "bare.zip", {"bare.car": b"x" * 10})
        i2 = carpack.describe(z2)
        check("a pack with no readme is still described",
              i2.error is None and i2.cars == ["bare.car"] and i2.readme is None)

        # Corrupt: recorded as an error, never raised.
        bad = tmp / "broken.zip"
        bad.write_bytes(b"this is not a zip file at all")
        i3 = carpack.describe(bad)
        check("a corrupt pack is recorded as an error, not raised",
              i3.error is not None and i3.sha256, (i3.error or "")[:40])
        check("  ...and it still carries a hash, so it can be identified",
              len(i3.sha256) == 64)

        print("\nthe .rar path\n")
        real = Path(sys.argv[1]) if len(sys.argv) > 1 else None
        if real is None:
            tree = (Path.home() / "Desktop" / "claude-code"
                    / "viper-racing-community-cars")
            real = next(tree.rglob("*.rar"), None) if tree.is_dir() else None
        if real is None or not real.is_file():
            print("  SKIPPED -- no .rar to hand. Pass one as an argument.")
        elif carpack.sevenzip() is None:
            print("  SKIPPED -- 7-Zip not found, so .rar cannot be read here.")
        else:
            i4 = carpack.describe(real, collection=real.parent.name)
            check("a real .rar is read", i4.error is None, (i4.error or "")[:60])
            check("  its members are listed", len(i4.members) > 0,
                  f"{len(i4.members)} members")
            check("  the archive itself is not listed as one of its members",
                  all(Path(m.name).name != real.name for m in i4.members))
            check("  sizes are real", all(m.size >= 0 for m in i4.members))

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
