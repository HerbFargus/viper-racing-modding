import sys, struct, re
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
EXE = r"C:\Users\seamus\Desktop\claude-code\reference-files\tools\community\aitweaker\ai-tweaker.exe"
b = open(EXE, "rb").read()
pe = struct.unpack_from("<I", b, 0x3c)[0]
nsec = struct.unpack_from("<H", b, pe + 6)[0]; opt = struct.unpack_from("<H", b, pe + 20)[0]
base = struct.unpack_from("<I", b, pe + 24 + 28)[0]
secs = []
for i in range(nsec):
    o = pe + 24 + opt + 40 * i
    name = b[o:o+8].rstrip(b"\0"); vs, va, rs, rp = struct.unpack_from("<IIII", b, o + 8)
    secs.append((name, base + va, vs, rp, rs))
def off(va):
    for n, v, vs, rp, rs in secs:
        if v <= va < v + max(vs, rs): return rp + va - v
def rd(va, n): o = off(va); return b[o:o+n]
def f32(va): return struct.unpack("<f", rd(va, 4))[0]
def f64(va): return struct.unpack("<d", rd(va, 8))[0]
syms = {}
for l in open("maplines.txt"):
    p = l.split()
    if len(p) >= 3:
        try: syms[int(p[2], 16)] = p[1]
        except ValueError: pass
def dis(start, end):
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    for ins in md.disasm(rd(start, end - start), start):
        s = f"{ins.address:08x} {ins.mnemonic:6} {ins.op_str}"
        for m in re.finditer(r"0x([0-9a-f]{6,8})", ins.op_str):
            a = int(m.group(1), 16)
            if a in syms: s += f"   ; {syms[a]}"
            elif "dword ptr [0x" in ins.op_str and 0x4c0000 < a < 0x600000:
                s += f"   ; f32={f32(a):.6g}"
            elif "qword ptr [0x" in ins.op_str and 0x4c0000 < a < 0x600000:
                s += f"   ; f64={f64(a):.6g}"
        print(s)
if __name__ == "__main__":
    dis(int(sys.argv[1], 16), int(sys.argv[2], 16))
