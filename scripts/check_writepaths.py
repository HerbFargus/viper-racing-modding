"""Check the write-path patches against real binaries.

Everything runs on COPIES in a temp folder -- never on the install passed in --
because the thing being verified is a byte patch on the game's engine.

Run:  python scripts/check_writepaths.py [Data-folder]
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import writepaths as wp  # noqa: E402

DEFAULT_DATA = (Path.home() / "Desktop" / "claude-code" / "game-files"
                / "installs" / "v1.0-RC")

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  {'ok   ' if ok else 'FAIL '} {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DATA
    binaries = [n for n in wp.TARGETS if (src / n).is_file()]
    if not binaries:
        print(f"no engine binary in {src}")
        sys.exit(1)
    print(f"source: {src}  ({', '.join(binaries)})\n")

    tmp = Path(tempfile.mkdtemp(prefix="check_writepaths_"))
    try:
        for n in binaries:
            shutil.copy2(src / n, tmp / n)
        # The source may already be patched -- it is a real install, not a
        # museum piece. Normalise the copies to unpatched so the test starts
        # from a known state whatever was passed in.
        for kind in (wp.USER_DIR_KIND, wp.LOGS_KIND):
            try:
                wp.revert(tmp, kind)
            except wp.PatchError:
                pass
        original = {n: sha(tmp / n) for n in binaries}
        sizes = {n: (tmp / n).stat().st_size for n in binaries}

        st = wp.status(tmp)
        live = wp.where(tmp)["binary"]
        check("a stock install reports its logs unpatched",
              all(v["logs"] == wp.UNPATCHED for v in st.values()))
        check("where() names the live binary", live == binaries[0], live)
        check("where() reports absolute log paths before patching",
              wp.where(tmp)["logs"].lower().startswith("c:"))

        # --- logs ---------------------------------------------------------
        rep = wp.apply(tmp, wp.LOGS_KIND)
        check("the log folder is created", Path(rep["folder"]).is_dir(),
              Path(rep["folder"]).name)
        check("the log folder is named 'log', not 'logs'",
              Path(rep["folder"]).name == wp.LOG_DIR, wp.LOG_DIR)
        check("BOTH log.log literals are patched, not just one",
              sum(1 for _, n in rep["changed"][live] if n.endswith("log.log")) == 2)
        check("logs report patched afterwards",
              wp.status(tmp)[live]["logs"] == wp.PATCHED)
        check("where() now reports relative log paths",
              not wp.where(tmp)["logs"].lower().startswith("c:"),
              wp.where(tmp)["logs"])
        check("file size is unchanged by the patch",
              all((tmp / n).stat().st_size == sizes[n] for n in binaries))
        check("re-applying is a no-op rather than an error",
              wp.apply(tmp, wp.LOGS_KIND)["changed"] == {})

        # --- user directory ----------------------------------------------
        if st[live]["userdir"] == wp.UNPATCHED:
            rep2 = wp.apply(tmp, wp.USER_DIR_KIND, migrate=False)
            check("the Config folder is created", Path(rep2["folder"]).is_dir())
            check("user dir reports patched",
                  wp.status(tmp)[live]["userdir"] == wp.PATCHED)
            check("the replacement has NO leading backslash (that would mean C:\\)",
                  not wp.USER_DIR_NEW.startswith(b"\\"),
                  wp.USER_DIR_NEW.decode())
        else:
            check("a build with no hardcoded user dir reports 'absent'",
                  st[live]["userdir"] == wp.ABSENT, st[live]["userdir"])

        # a release-lineage race.bin must never be reported as patched, even
        # though its own "\Config\" literal ends with our replacement
        if "race.bin" in binaries and "race.bin" != live:
            check("the release build's \\Config\\ is not mistaken for our patch",
                  wp.status(tmp)["race.bin"]["userdir"] == wp.ABSENT,
                  wp.status(tmp)["race.bin"]["userdir"])

        # --- revert --------------------------------------------------------
        wp.revert(tmp, wp.USER_DIR_KIND)
        wp.revert(tmp, wp.LOGS_KIND)
        check("revert restores every binary byte-for-byte",
              all(sha(tmp / n) == original[n] for n in binaries))
        check("status returns to unpatched",
              all(v["logs"] == wp.UNPATCHED for v in wp.status(tmp).values()))

        # --- refuses what it should ---------------------------------------
        empty = tmp / "empty"
        empty.mkdir()
        try:
            wp.apply(empty, wp.LOGS_KIND)
            check("refuses a folder with no engine binary", False)
        except wp.PatchError:
            check("refuses a folder with no engine binary", True)

        half = tmp / "half"
        half.mkdir()
        # from the normalised copy, not src -- src may already be patched
        shutil.copy2(tmp / live, half / live)
        blob = (half / live).read_bytes()
        one = wp._sites(blob, b"c:\\log.log")[0]
        patched = bytearray(blob)
        patched[one:one + 12] = b"log\\log.log\x00"
        (half / live).write_bytes(bytes(patched))
        try:
            wp.apply(half, wp.LOGS_KIND)
            check("refuses a half-patched binary rather than guessing", False)
        except wp.PatchError:
            check("refuses a half-patched binary rather than guessing", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{checks - len(failures)}/{checks} passed")
    if failures:
        for f in failures:
            print(f"  FAILED: {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
