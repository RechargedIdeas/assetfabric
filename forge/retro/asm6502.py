"""Tiny two-pass 6502 assembler with a cycle table — the ROMBuilder's CodeGen backend and the C1 *cycle predictor*
(ASSETFABRIC_SPEC §5.1 "C1 Console constraint solvers / palette / cycle predictors").

Syntax (one statement per line, `;` comments):
    label:                    .org $8000            .byte $01, 2, <label, >label
    .word label, $1234        .res 16 [, fill]      NAME = $42      (constants)
    LDA #$10 / LDA zp / LDA abs / LDA abs,X / LDA abs,Y / LDA zp,X / LDA (zp),Y / LDA (zp,X) / JMP (abs) / BNE label
Operands accept $hex, %bin, decimal, labels/constants, <x (low byte), >x (high byte) and a single +/- offset.
A plain operand < $100 that is a number or a constant assembles as zero page when the opcode has that mode.

`cycles(start_label, end_label)` sums the *worst-case* cycle count of the straight-line code between two labels
(page-cross penalties included; branches counted as taken across a page). It refuses code that branches backwards
inside the window, so a predicted bound is always a real bound.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# opcode, mode -> (byte, base cycles, page-cross penalty)
_T: dict[tuple[str, str], tuple[int, int, int]] = {}


def _add(op: str, rows: str) -> None:
    for item in rows.split():
        mode, code, cyc = item.split(":")
        pen = 1 if cyc.endswith("+") else 0
        _T[(op, mode)] = (int(code, 16), int(cyc.rstrip("+")), pen)


for _op, _rows in {
    "ADC": "imm:69:2 zp:65:3 zpx:75:4 abs:6D:4 absx:7D:4+ absy:79:4+ indx:61:6 indy:71:5+",
    "AND": "imm:29:2 zp:25:3 zpx:35:4 abs:2D:4 absx:3D:4+ absy:39:4+ indx:21:6 indy:31:5+",
    "ASL": "acc:0A:2 zp:06:5 zpx:16:6 abs:0E:6 absx:1E:7",
    "BIT": "zp:24:3 abs:2C:4",
    "CMP": "imm:C9:2 zp:C5:3 zpx:D5:4 abs:CD:4 absx:DD:4+ absy:D9:4+ indx:C1:6 indy:D1:5+",
    "CPX": "imm:E0:2 zp:E4:3 abs:EC:4", "CPY": "imm:C0:2 zp:C4:3 abs:CC:4",
    "DEC": "zp:C6:5 zpx:D6:6 abs:CE:6 absx:DE:7", "INC": "zp:E6:5 zpx:F6:6 abs:EE:6 absx:FE:7",
    "EOR": "imm:49:2 zp:45:3 zpx:55:4 abs:4D:4 absx:5D:4+ absy:59:4+ indx:41:6 indy:51:5+",
    "JMP": "abs:4C:3 ind:6C:5", "JSR": "abs:20:6",
    "LDA": "imm:A9:2 zp:A5:3 zpx:B5:4 abs:AD:4 absx:BD:4+ absy:B9:4+ indx:A1:6 indy:B1:5+",
    "LDX": "imm:A2:2 zp:A6:3 zpy:B6:4 abs:AE:4 absy:BE:4+",
    "LDY": "imm:A0:2 zp:A4:3 zpx:B4:4 abs:AC:4 absx:BC:4+",
    "LSR": "acc:4A:2 zp:46:5 zpx:56:6 abs:4E:6 absx:5E:7",
    "ORA": "imm:09:2 zp:05:3 zpx:15:4 abs:0D:4 absx:1D:4+ absy:19:4+ indx:01:6 indy:11:5+",
    "ROL": "acc:2A:2 zp:26:5 zpx:36:6 abs:2E:6 absx:3E:7", "ROR": "acc:6A:2 zp:66:5 zpx:76:6 abs:6E:6 absx:7E:7",
    "SBC": "imm:E9:2 zp:E5:3 zpx:F5:4 abs:ED:4 absx:FD:4+ absy:F9:4+ indx:E1:6 indy:F1:5+",
    "STA": "zp:85:3 zpx:95:4 abs:8D:4 absx:9D:5 absy:99:5 indx:81:6 indy:91:6",
    "STX": "zp:86:3 zpy:96:4 abs:8E:4", "STY": "zp:84:3 zpx:94:4 abs:8C:4",
}.items():
    _add(_op, _rows)
for _op, _code in {"BPL": 0x10, "BMI": 0x30, "BVC": 0x50, "BVS": 0x70, "BCC": 0x90, "BCS": 0xB0, "BNE": 0xD0, "BEQ": 0xF0}.items():
    _T[(_op, "rel")] = (_code, 2, 2)     # +1 taken, +1 more across a page → worst case 4
for _op, _code, _c in [("BRK", 0x00, 7), ("CLC", 0x18, 2), ("CLD", 0xD8, 2), ("CLI", 0x58, 2), ("CLV", 0xB8, 2),
                       ("DEX", 0xCA, 2), ("DEY", 0x88, 2), ("INX", 0xE8, 2), ("INY", 0xC8, 2), ("NOP", 0xEA, 2),
                       ("PHA", 0x48, 3), ("PHP", 0x08, 3), ("PLA", 0x68, 4), ("PLP", 0x28, 4), ("RTI", 0x40, 6),
                       ("RTS", 0x60, 6), ("SEC", 0x38, 2), ("SED", 0xF8, 2), ("SEI", 0x78, 2), ("TAX", 0xAA, 2),
                       ("TAY", 0xA8, 2), ("TSX", 0xBA, 2), ("TXA", 0x8A, 2), ("TXS", 0x9A, 2), ("TYA", 0x98, 2)]:
    _T[(_op, "imp")] = (_code, _c, 0)

_SIZE = {"imp": 1, "acc": 1, "imm": 2, "zp": 2, "zpx": 2, "zpy": 2, "rel": 2, "indx": 2, "indy": 2,
         "abs": 3, "absx": 3, "absy": 3, "ind": 3}


class AsmError(ValueError):
    pass


@dataclass
class Program:
    origin: int
    data: bytearray
    labels: dict[str, int]
    listing: list[tuple[int, str, str, int]] = field(default_factory=list)   # (addr, op, mode, worst cycles)

    def cycles(self, start: str, end: str) -> int:
        a, b = self.labels[start], self.labels[end]
        total = 0
        for addr, op, mode, cyc in self.listing:
            if a <= addr < b:
                if mode == "rel":
                    off = self.data[addr - self.origin + 1]
                    if off >= 0x80:
                        raise AsmError(f"backward branch at ${addr:04X} inside cycle window {start}..{end}")
                total += cyc
        return total


def _num(tok: str, syms: dict[str, int], strict: bool) -> tuple[int, bool]:
    """→ (value, is_known_small) where is_known_small says the token can be zero page."""
    tok = tok.strip()
    m = re.match(r"^(.*?)([+-])(\$?[0-9A-Fa-f]+|%[01]+|\d+)$", tok)
    if m and m.group(1) and not m.group(1).endswith(("<", ">")):
        base, zp = _num(m.group(1), syms, strict)
        off = _num(m.group(3), syms, strict)[0]
        v = base + off if m.group(2) == "+" else base - off
        return v, zp and 0 <= v < 0x100
    if tok.startswith("<"):
        return _num(tok[1:], syms, strict)[0] & 0xFF, True
    if tok.startswith(">"):
        return (_num(tok[1:], syms, strict)[0] >> 8) & 0xFF, True
    if tok.startswith("$"):
        v = int(tok[1:], 16)
        return v, v < 0x100 and len(tok) <= 3
    if tok.startswith("%"):
        v = int(tok[1:], 2)
        return v, v < 0x100
    if tok.isdigit():
        v = int(tok)
        return v, v < 0x100
    if tok in syms:
        v = syms[tok]
        return v, v < 0x100 and tok in _CONST_NAMES
    if strict:
        raise AsmError(f"unknown symbol {tok!r}")
    return 0x1234, False


_CONST_NAMES: set[str] = set()


def _mode(op: str, arg: str, syms: dict[str, int], strict: bool) -> tuple[str, int]:
    a = arg.strip()
    if not a:
        return ("acc" if (op, "acc") in _T else "imp"), 0
    if a.upper() == "A":
        return "acc", 0
    if (op, "rel") in _T:
        return "rel", _num(a, syms, strict)[0]
    if a.startswith("#"):
        return "imm", _num(a[1:], syms, strict)[0] & 0xFF
    m = re.match(r"^\((.+)\),\s*[Yy]$", a)
    if m:
        return "indy", _num(m.group(1), syms, strict)[0]
    m = re.match(r"^\((.+),\s*[Xx]\)$", a)
    if m:
        return "indx", _num(m.group(1), syms, strict)[0]
    m = re.match(r"^\((.+)\)$", a)
    if m:
        return "ind", _num(m.group(1), syms, strict)[0]
    idx = ""
    m = re.match(r"^(.+),\s*([XxYy])$", a)
    if m:
        a, idx = m.group(1), m.group(2).lower()
    v, small = _num(a, syms, strict)
    if small and (op, "zp" + idx) in _T:
        return "zp" + idx, v
    return "abs" + idx, v


def assemble(src: str, origin: int = 0x8000) -> Program:
    _CONST_NAMES.clear()
    lines = []
    for raw in src.splitlines():
        line = raw.split(";", 1)[0].rstrip()
        if line.strip():
            lines.append(line.strip())
    syms: dict[str, int] = {}
    for line in lines:
        m = re.match(r"^([A-Za-z_]\w*)\s*=\s*(.+)$", line)
        if m:
            syms[m.group(1)] = _num(m.group(2), syms, True)[0]
            _CONST_NAMES.add(m.group(1))
    for strict in (False, True):
        pc = origin
        out = bytearray()
        listing = []
        for line in lines:
            if re.match(r"^[A-Za-z_]\w*\s*=", line):
                continue
            while True:
                m = re.match(r"^([A-Za-z_]\w*):\s*(.*)$", line)
                if not m:
                    break
                if not strict:
                    if m.group(1) in syms and m.group(1) not in _CONST_NAMES and syms[m.group(1)] != pc:
                        raise AsmError(f"duplicate label {m.group(1)}")
                    syms[m.group(1)] = pc
                line = m.group(2)
            if not line:
                continue
            parts = line.split(None, 1)
            op, arg = parts[0].upper(), (parts[1] if len(parts) > 1 else "")
            if op == ".ORG":
                new = _num(arg, syms, True)[0]
                if new < pc:
                    raise AsmError(".org moves backwards")
                out += bytes(new - pc)
                pc = new
                continue
            if op == ".BYTE":
                for t in arg.split(","):
                    out.append(_num(t, syms, strict)[0] & 0xFF)
                    pc += 1
                continue
            if op == ".WORD":
                for t in arg.split(","):
                    v = _num(t, syms, strict)[0]
                    out += bytes((v & 0xFF, (v >> 8) & 0xFF))
                    pc += 2
                continue
            if op == ".RES":
                bits = [t.strip() for t in arg.split(",")]
                n = _num(bits[0], syms, True)[0]
                fill = _num(bits[1], syms, True)[0] if len(bits) > 1 else 0
                out += bytes([fill & 0xFF]) * n
                pc += n
                continue
            mode, val = _mode(op, arg, syms, strict)
            if (op, mode) not in _T:
                raise AsmError(f"{op} has no {mode} mode: {line!r}")
            code, cyc, pen = _T[(op, mode)]
            size = _SIZE[mode]
            out.append(code)
            if mode == "rel":
                off = val - (pc + 2)
                if strict and not -128 <= off <= 127:
                    raise AsmError(f"branch out of range: {line!r}")
                out.append(off & 0xFF)
            elif size == 2:
                if strict and val > 0xFF:
                    raise AsmError(f"operand > $FF: {line!r}")
                out.append(val & 0xFF)
            elif size == 3:
                out += bytes((val & 0xFF, (val >> 8) & 0xFF))
            listing.append((pc, op, mode, cyc + pen))
            pc += size
    return Program(origin, out, {k: v for k, v in syms.items() if k not in _CONST_NAMES}, listing)
