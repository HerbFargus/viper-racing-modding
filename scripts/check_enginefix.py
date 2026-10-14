"""Check vrmod.enginefix against every engine build on hand.

For each build: both fixes are found stock exactly once; applying them leaves the expected bytes
(and, on race.bin, a jump into a stub in the .text slack that jumps back to the right place);
a second apply changes nothing; race.bin reverts byte for byte, and race.exe refuses to revert
without touching anything. Then the interplay with needlefix, the other user of the .text slack:
in either order their stubs must not overlap.

    python scripts/check_enginefix.py [extra engine files...]

Default sources: the reference engine builds and the test install's pristine race.exe snapshot.
"""
import shutil
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capstone import CS_ARCH_X86, CS_MODE_32, Cs  # noqa: E402

from vrmod import enginefix as E, needlefix, pe  # noqa: E402

ROOT = Path.home() / "Desktop" / "claude-code"
DEFAULTS = sorted((ROOT / "reference-files" / "executables" / "engine-builds").glob("race.bin-*.bin")) + \
           [ROOT / "game-files" / "installs" / "v1.0-RC" / "race.exe.vrmod-original"]

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  {'ok   ' if ok else 'FAIL '} {name}" + (f"  ({detail})" if detail else ""))
    if not ok:
        failures.append(name)


def disasm(blob: bytes, off: int, n: int) -> list:
    va = pe.offset_to_va(blob, off)
    return list(Cs(CS_ARCH_X86, CS_MODE_32).disasm(blob[off:off + n], va))


def one_build(path: Path) -> None:
    print(f"\n--- {path.name} ({path.stat().st_size:,} bytes)")
    stock = path.read_bytes()
    is_exe = E._one(E.EXE_STOCK, stock, "advance_bead") is not None
    check("both fixes found stock", E.status_bytes(stock) == {"obstacle_wake": E.STOCK, "ai_bead_guard": E.STOCK},
          str(E.status_bytes(stock)))
    blob = bytearray(stock)
    done = E.apply_bytes(blob)
    fixed = bytes(blob)
    check("both fixed after apply", E.status_bytes(fixed) == {"obstacle_wake": E.FIXED, "ai_bead_guard": E.FIXED})
    changed = [i for i in range(len(stock)) if stock[i] != fixed[i]]
    check("the file length is unchanged", len(fixed) == len(stock))

    # wake: exactly the 3 bytes, now NOPs, falling into Perturb
    w = E._one(E.WAKE_FIXED, fixed, "Obstacle::Reset").start() + E.WAKE_AT
    ins = disasm(fixed, w, 6)
    check("Reset's ret is now three NOPs, then Perturb's push esi",
          [i.mnemonic for i in ins[:4]] == ["nop", "nop", "nop", "push"])

    if is_exe:
        m = E._one(E.EXE_FIXED, fixed, "advance_bead")
        at = m.start() + len(E._EXE_HEAD)
        text = [f"{i.mnemonic} {i.op_str}" for i in disasm(fixed, at, 32)]
        check("race.exe: the guard reads as intended", text[:7] == [
            "mov dword ptr [esp + 0x2c], 0xffffffff", "xor ebx, ebx", "cmp dword ptr [edi + 4], 0",
            f"jne {pe.offset_to_va(fixed, at) + 25:#x}", "mov eax, dword ptr [edi + 0x2c]",
            "mov dword ptr [edi + 4], eax", "mov dword ptr [edi + 8], ebx"], "; ".join(text[:7]))
        check("race.exe: 35 bytes changed, all inside the two sites",
              len(changed) <= 35 and all(w <= c < w + 3 or at <= c < at + 32 for c in changed), f"{len(changed)}")
        before = bytes(blob)
        try:
            E.revert_bytes(blob)
            check("race.exe: revert refuses", False)
        except E.EngineFixError:
            check("race.exe: revert refuses and changes nothing", bytes(blob) == before)
    else:
        m = E._one(E.BIN_FIXED, fixed, "advance_bead")
        src = m.start() + E.BIN_AT
        stub = E._bin_stub_at(fixed, m)
        j = disasm(fixed, src, 6)
        check("race.bin: the loads became jmp + nop", [i.mnemonic for i in j] == ["jmp", "nop"])
        check("race.bin: the jump lands on the stub", int(j[0].op_str, 16) == pe.offset_to_va(fixed, stub))
        _name, _va, vsize, rawptr, rawsize = needlefix._text(fixed)
        check("race.bin: the stub is in .text's mapped slack", rawptr + vsize <= stub and stub + E.BIN_STUB_LEN <= rawptr + rawsize,
              f"stub {stub:#x}, slack {rawptr + vsize:#x}..{rawptr + rawsize:#x}")
        s = disasm(fixed, stub, E.BIN_STUB_LEN)
        check("race.bin: the stub checks, re-homes, reloads and jumps back to after the loads",
              [i.mnemonic for i in s] == ["cmp", "jne", "mov", "mov", "mov", "mov", "mov", "jmp"]
              and int(s[-1].op_str, 16) == pe.offset_to_va(fixed, src) + 6
              and int(s[1].op_str, 16) == s[5].address)
        rev = bytearray(fixed)
        E.revert_bytes(rev)
        check("race.bin: revert restores every byte", bytes(rev) == stock)

    again = bytearray(fixed)
    d2 = E.apply_bytes(again)
    check("a second apply changes nothing", bytes(again) == fixed and set(d2.values()) == {"already fixed"})

    # needlefix shares the .text slack: both orders must leave two separate stubs
    for order in ("needle first", "enginefix first"):
        tmp = Path(tempfile.mkdtemp(prefix="check_enginefix_"))
        try:
            name = "race.exe" if is_exe else "race.bin"
            (tmp / name).write_bytes(stock)
            if order == "needle first":
                needlefix.apply(tmp)
                E.apply(tmp)
            else:
                E.apply(tmp)
                needlefix.apply(tmp)
            out = (tmp / name).read_bytes()
            ok = E.status_bytes(out) == {"obstacle_wake": E.FIXED, "ai_bead_guard": E.FIXED} \
                and needlefix.status(tmp) not in (needlefix.MISSING,)
            if not is_exe:
                stub = E._bin_stub_at(out, E._one(E.BIN_FIXED, out, "advance_bead"))
                ok = ok and out[stub:stub + len(E.BIN_STUB_BODY)] == E.BIN_STUB_BODY
            check(f"with needlefix ({order}): both still intact", ok, needlefix.status(tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    paths = [p for p in DEFAULTS + [Path(a) for a in sys.argv[1:]] if p.is_file()]
    if not paths:
        print("no engine builds found")
        sys.exit(1)
    for p in paths:
        one_build(p)
    try:
        E.apply_bytes(bytearray(b"MZ" + bytes(4096)))
        check("an unrecognised file is refused", False)
    except E.EngineFixError:
        check("an unrecognised file is refused", True)
    print(f"\n{checks - len(failures)}/{checks} checks passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
