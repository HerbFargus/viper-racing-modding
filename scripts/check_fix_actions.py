"""Checks that every one-click fix doctor offers actually has a handler.

THE BUG THIS EXISTS FOR. Doctor attaches an `action` id to a Finding when the
tool can fix the thing itself, and the desktop UI renders that as a button. The
handler used to be a chain of `if action == ...` inside the request handler, and
it fell behind twice without anyone noticing: doctor grew a `modassert` action
(#77) and a `carlist` action (#83), neither was added, and pressing those buttons
answered

    unknown fix: modassert

Nothing caught it. The findings looked right, the buttons rendered, the CLI
worked -- only the click was dead, and only on installs in the state that
produces those findings. It was found by a user pressing one.

So the handlers are a registry (`switcher_ui.FIX_ACTIONS`) rather than a
statement chain, and this asserts the two sets agree in BOTH directions: no
finding offers a button that does nothing, and no handler sits there for a
finding that no longer exists.

Static only -- no game files, no server.

    python scripts/check_fix_actions.py
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vrmod import doctor, switcher_ui  # noqa: E402

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok    {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def main() -> int:
    src = Path(inspect.getfile(doctor)).read_text(encoding="utf-8")
    emitted = set(re.findall(r'action="([a-z_]+)"', src))
    handled = set(switcher_ui.FIX_ACTIONS)

    print(f"  doctor offers  : {', '.join(sorted(emitted))}")
    print(f"  the UI handles : {', '.join(sorted(handled))}\n")

    check("doctor offers at least one fix", bool(emitted), f"{len(emitted)} actions")

    dead = sorted(emitted - handled)
    check("every action doctor offers has a handler -- no dead buttons",
          not dead, ", ".join(dead) if dead else "none")

    orphan = sorted(handled - emitted)
    check("every handler is reachable from some finding",
          not orphan, ", ".join(orphan) if orphan else "none")

    # The two that went missing, named outright so a regression is obvious.
    for a in ("modassert", "carlist"):
        check(f"  {a} specifically is wired up", a in handled and a in emitted)

    check("every handler is callable", all(callable(f) for f in
                                           switcher_ui.FIX_ACTIONS.values()))

    # Each handler takes exactly the Data folder. A handler with a different
    # shape would raise at click time, which is the failure mode being avoided.
    bad = []
    for name, fn in switcher_ui.FIX_ACTIONS.items():
        try:
            n = len(inspect.signature(fn).parameters)
        except (TypeError, ValueError):
            n = -1
        if n != 1:
            bad.append(f"{name} takes {n}")
    check("every handler takes exactly one argument (the Data folder)",
          not bad, ", ".join(bad) if bad else "none")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
