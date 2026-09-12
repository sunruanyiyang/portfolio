#!/usr/bin/env python3
"""
verify_netlist.py — independent 64-input gate-level re-simulator.

Parses a structural Verilog netlist over the Nangate 45nm X1 cell subset
(including X2/X4/X8/X16/X32 drive variants, which share the same logic),
simulates all 64 input patterns, and compares the output against a target
truth table. This is an INDEPENDENT check written during repository
curation; it does not use Yosys, ABC or the SAT framework.

Supported netlist styles:
  * `module y0 ( input [5:0] x, output y0 );` with `x[k]` bit references;
  * `module y2_beh(x5,x4,x3,x2,x1,x0,y2);` with bare per-bit input ports
    and `assign` aliases (`assign _50_ = x0;`);
  * `assign`-based outputs (`assign y2 = _56_;`).

Usage:
    python3 verify_netlist.py rtl/optimized/y0_final.v --truth 0x45D3356F02C1D7D8
    python3 verify_netlist.py rtl/optimized/y2_final.v --sbox-bit 2
    python3 verify_netlist.py <netlist.v> --truth <hex> --output y0

The --sbox-bit option derives the target from the official Dillon
permutation (the ground truth embedded in verification/verify.v).
"""

from __future__ import annotations

import argparse
import re
import sys

# Official Dillon permutation (competition testbench, verification/verify.v).
DILLON = [
    0x00, 0x36, 0x30, 0x0d, 0x0f, 0x12, 0x35, 0x23,
    0x19, 0x3f, 0x2d, 0x34, 0x03, 0x14, 0x29, 0x21,
    0x3b, 0x24, 0x02, 0x22, 0x0a, 0x08, 0x39, 0x25,
    0x3c, 0x13, 0x2a, 0x0e, 0x32, 0x1a, 0x3a, 0x18,
    0x27, 0x1b, 0x15, 0x11, 0x10, 0x1d, 0x01, 0x3e,
    0x2f, 0x28, 0x33, 0x38, 0x07, 0x2b, 0x2c, 0x26,
    0x1f, 0x0b, 0x04, 0x1c, 0x3d, 0x2e, 0x05, 0x31,
    0x09, 0x06, 0x17, 0x20, 0x1e, 0x0c, 0x37, 0x16,
]

PINOUT_KEYS = ("Y", "ZN", "Z")


def sbox_bit_truth(bit: int) -> int:
    """Truth table of output bit `bit` of the Dillon permutation."""
    tt = 0
    for m in range(64):
        tt |= (((DILLON[m] >> bit) & 1) << m)
    return tt


def _base_cell(cell: str) -> str:
    """'INV_X32' -> 'INV'; 'NAND2_X1' -> 'NAND2'."""
    return re.sub(r"_X\d+$", "", cell)


def cell_eval(cell: str, d: dict[str, int]) -> int:
    """Evaluate one gate instance. `d` maps input pin names to values."""
    c = _base_cell(cell)
    if c == "INV":
        return 1 - d["A"]
    if c == "BUF":
        return d["A"]
    if c == "NAND2":
        return 1 - (d["A1"] & d["A2"])
    if c == "NAND3":
        return 1 - (d["A1"] & d["A2"] & d["A3"])
    if c == "NAND4":
        return 1 - (d["A1"] & d["A2"] & d["A3"] & d["A4"])
    if c == "NOR2":
        return 1 - (d["A1"] | d["A2"])
    if c == "AND2":
        return d["A1"] & d["A2"]
    if c == "AND3":
        return d["A1"] & d["A2"] & d["A3"]
    if c == "XNOR2":
        return 1 - (d["A1"] ^ d["A2"])
    if c in ("OAI21", "AOI21", "OAI22", "AOI22"):
        # Nangate semantics differ by pin convention:
        #   A1/A2/B1 style: OAI21 = ~((A1|A2) & B1), AOI21 = ~((A1&A2) | B1)
        #   A/B1/B2 style:  OAI21 = ~(A & (B1|B2)), AOI21 = ~(A | (B1&B2))
        if c == "OAI21":
            if "A1" in d:
                return 1 - ((d["A1"] | d["A2"]) & d["B1"])
            return 1 - (d["A"] & (d["B1"] | d["B2"]))
        if c == "AOI21":
            if "A1" in d:
                return 1 - ((d["A1"] & d["A2"]) | d["B1"])
            return 1 - (d["A"] | (d["B1"] & d["B2"]))
        if c == "OAI22":
            return 1 - ((d["A1"] | d["A2"]) & (d["B1"] | d["B2"]))
        if c == "AOI22":
            return 1 - ((d["A1"] & d["A2"]) | (d["B1"] & d["B2"]))
    raise ValueError(f"unsupported cell type: {cell}")


def parse_netlist(path: str):
    """Return (cells, assigns, default_output) parsed from a netlist."""
    src = open(path, encoding="utf-8").read()
    m = re.search(r"module\s+\w+\s*(?:\([^)]*\))?\s*;\s*(.*?)endmodule", src, re.S)
    if not m:
        raise ValueError("no module body found")
    body = m.group(1)
    cells = []
    for cell, inst, args in re.findall(
        r"^\s*([A-Z0-9_]+_X\d+)\s+(\w+)\s*\((.*?)\)\s*;", body, re.M | re.S
    ):
        pins = [(p, w.strip()) for p, w in re.findall(r"\.(\w+)\s*\(([^)]*)\)", args)]
        out = [w for p, w in pins if p in PINOUT_KEYS]
        if not out:
            raise ValueError(f"cell {inst}: no output pin")
        cells.append((cell, inst, pins, out[0]))
    assigns = [(a.strip(), e.strip()) for a, e in re.findall(r"assign\s+(\w+)\s*=\s*([^;]+);", body)]
    default_out = None
    if assigns:
        default_out = assigns[-1][0]
    elif cells:
        default_out = cells[-1][3]
    return cells, assigns, default_out


def simulate(cells, assigns, output: str) -> int:
    """Simulate all 64 patterns; return packed truth table (bit m = f(m))."""
    tt = 0
    for x in range(64):
        wires: dict[str, int] = {}

        def sig(s: str) -> int:
            mm = re.fullmatch(r"\s*x\[(\d)\]\s*", s)
            if mm:
                return (x >> int(mm.group(1))) & 1
            bm = re.fullmatch(r"\s*x(\d)\s*", s)
            if bm:
                return (x >> int(bm.group(1))) & 1
            return wires[s]

        # 1) resolve assign aliases whose RHS is directly resolvable
        #    (x[k], xN, or an already-resolved wire); repeat to fixpoint
        pending = list(assigns)
        while pending:
            progressed = False
            rest = []
            for lhs, rhs in pending:
                if re.fullmatch(r"\s*x\[\d\]\s*|\s*x\d\s*", rhs):
                    wires[lhs] = sig(rhs)
                    progressed = True
                elif rhs in wires:
                    wires[lhs] = wires[rhs]
                    progressed = True
                else:
                    rest.append((lhs, rhs))
            pending = rest
            if not progressed:
                break  # remaining assigns depend on gate outputs

        # 2) evaluate gates in netlist order
        for cell, _inst, pins, outname in cells:
            d = {p: sig(w) for p, w in pins if p not in PINOUT_KEYS}
            wires[outname] = cell_eval(cell, d)

        # 3) resolve any remaining assigns (e.g. output = gate wire)
        for lhs, rhs in pending:
            if rhs in wires:
                wires[lhs] = wires[rhs]

        tt |= (wires[output] << x)
    return tt


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("netlist", help="structural Verilog netlist (*_X<n> cells)")
    ap.add_argument(
        "--truth", help="expected 64-bit truth table as hex, e.g. 0x45D3356F02C1D7D8"
    )
    ap.add_argument(
        "--sbox-bit", type=int, choices=range(6),
        help="expected = bit N of the Dillon permutation",
    )
    ap.add_argument(
        "--output", default=None,
        help="output wire name (default: last assign target / last cell output)",
    )
    args = ap.parse_args()

    if (args.truth is None) == (args.sbox_bit is None):
        ap.error("exactly one of --truth / --sbox-bit is required")

    expected = int(args.truth, 16) if args.truth else sbox_bit_truth(args.sbox_bit)

    cells, assigns, default_out = parse_netlist(args.netlist)
    if not cells:
        ap.error(
            "no *_X<n> cells found in the netlist — this tool only supports "
            "synthesized gate netlists (not RTL-style wire assignments)"
        )
    output = args.output or default_out
    if output is None:
        ap.error("cannot determine output wire; pass --output")

    got = simulate(cells, assigns, output)

    ok = got == expected
    print(f"netlist : {args.netlist}")
    print(f"output  : {output}")
    print(f"expected: 64'h{expected:016X}")
    print(f"got     : 64'h{got:016X}")
    print("RESULT  : " + ("MATCH ✓" if ok else "MISMATCH ✗"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
