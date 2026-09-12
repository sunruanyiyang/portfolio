# Low-Latency Boolean Circuit Synthesis for 6-bit S-Boxes

Research project on synthesizing low-delay gate-level implementations of the
single-output Boolean functions of a 6-input S-box.

> **Repository status (2026-09)**: this snapshot contains the complete,
> runnable synthesis stack plus the results that are independently verified.
> The y1 / y2 final netlists are **not** included — they fail the ground
> truth check (see [Verified results](#verified-results)).

## Objective

Minimize the critical-path delay of each output function when mapped to a
standard-cell library. **Area is not the primary optimization objective** —
the target metric is the STA-measured critical-path delay in picoseconds.

## Target function

The S-box is the official "Dillon permutation" 6×6 substitution used in the
competition testbench (`verification/verify.v`), with input convention
`x0..x5 = x[0..5]`. The six output bits `y0..y5` are the bits of `P[x]`
(`problem/truth_tables.md` lists the full table and the derived truth
tables). The canonical single-output functions are:

| output | truth table (64-bit, little-endian minterm index) |
|---|---|
| y0 | `0x45D3356F02C1D7D8` |
| y1 | `0xD623B5837E1D12B2` |
| y2 | `0xF67DD1A509822E5A` |
| y3 | `0x313B6BA2ED714718` |
| y4 | `0xD4990CBEF3412B66` |
| y5 | `0x48B0EF8155CBCEC6` |

## Method evolution

```
Yosys / ABC baseline
    → Manual structural optimization
    → Heuristic Shannon-decomposition search  (search/)
    → Gate-template search                    (search/template_search.py)
    → SAT-based exact synthesis               (exact_synthesis/)
        truth table → CNF → kissat → circuit recovery → Verilog
    → ABC delay-oriented deep synthesis       (scripts/abc_optimize.ys)
    → STA verification                        (scripts/sta.tcl, OpenSTA)
```

* `search/` — heuristic two-layer Shannon decomposition search over split
  variable orders (e.g. `x2 → x4 → x5`), generating structural Verilog and
  measuring each candidate through Yosys/ABC (`results/all_results.csv`,
  `results/y0_best_2_4_5_156.83ps.dot`).
* `exact_synthesis/` — **SAT-based exact synthesis framework** (the
  engineering core of this project): encodes the existence of a
  delay-bounded circuit as a DIMACS CNF instance (`encoder/`), solves it
  with the external `kissat` binary (`solver/run_kissat.py`), and recovers
  the circuit back to Verilog (`recover/`). Key engineering features:
  * static CNF caching — delay-independent clauses (structure + symmetry +
    function) are encoded **once** per gate budget as a raw DIMACS body
    file and reused across the binary search over delay bounds;
  * binary search over delay bounds per gate budget (each delay hypothesis
    is a fresh kissat invocation on a self-contained CNF);
  * streaming DIMACS writer (O(1) memory in the number of clauses);
  * regression suite asserting encoding tightness (optimal − 1 gates is
    UNSAT) and soundness (recovered circuit passes independent functional
    simulation): `python3 exact_synthesis/test_regression.py`.
* `scripts/` — the Yosys/ABC flows (`abc_baseline.ys`, `abc_optimize.ys`)
  and the OpenSTA timing script (`sta.tcl`).

## Verified results

| output | delay | status |
|---|---|---|
| y0 | **123.03 ps** | ✅ `rtl/optimized/y0_final.v` (27 gates, depth 5, area 24.96). **Independently re-verified** with a 64-input gate-level simulation — it exactly implements `0x45D3356F02C1D7D8`. |

**y1 and y2 are not included.** Every y1/y2 netlist available in the
project files (e.g. `y1_FINAL_fixed_best.v`, `y2_FINAL_fixed_best.v`,
`y2_FINAL_full_best.v`, `y2_mapped.v`) implements a function that does
**not** match this S-box's ground truth, despite header comments claiming
"ABC cec + 64-input simulation". Independently re-simulated:

| file (not in repo) | implements | canonical bit | match |
|---|---|---|---|
| `y1_FINAL_fixed_best.v` | `0x1EF2BA4B1A8CC3D9` | y1 = `0xD623B5837E1D12B2` | ✗ |
| `y2_FINAL_fixed_best.v` | `0x0D8D35B8659ADC24` | y2 = `0xF67DD1A509822E5A` | ✗ |
| `y2_FINAL_full_best.v` | `0x0D8D35B8659ADC24` | y2 = `0xF67DD1A509822E5A` | ✗ |
| `y2_mapped.v` | `0x243B59A61DACB1B0` | y2 = `0xF67DD1A509822E5A` | ✗ |

None of them matches any output bit of the Dillon permutation under any
input-variable permutation or polarity. Until netlists that pass
verification are produced, no y1/y2 delay numbers are published here.

## Verification

- 64-input exhaustive simulation: `verification/verify.v` (original
  testbench, ground truth) and `verification/verify_netlist.py`
  (independent gate-level re-simulator).
- Independent functional re-simulation inside the SAT pipeline
  (`exact_synthesis/recover/verify.py`) — the recovered circuit is checked
  against the truth table directly, not just trusted from the SAT model.
- ABC CEC (equivalence checking) — used during development.
- Nangate 45nm static timing analysis via OpenSTA (`scripts/sta.tcl`).

Reproduce the y0 check:

```bash
python3 verification/verify_netlist.py rtl/optimized/y0_final.v --sbox-bit 0
# expected: MATCH ✓ (64'h45D3356F02C1D7D8)
```

## Repository layout

```
sbox-low-latency-synthesis/
├── README.md
├── requirements.txt
├── LICENSE                      # template — choose a license and fill in
├── problem/                     # problem definition, truth tables, gate library
├── rtl/
│   ├── original/SB.v            # original full S-box (ANF) — matches the permutation
│   └── optimized/y0_final.v     # verified final y0 netlist (123.03 ps)
├── search/                      # heuristic decomposition / template search
├── exact_synthesis/             # SAT-based exact synthesis (CNF → kissat → Verilog)
│   ├── synthesize.py            # top-level driver: gate-budget × delay binary search
│   ├── encoder/                 # truth table, variables, structure/function/delay,
│   │                            #   symmetry-breaking encoders, streaming DIMACS writer
│   ├── solver/run_kissat.py     # external kissat invocation + result parsing
│   ├── recover/                 # extract circuit from SAT model, emit Verilog, verify
│   ├── test_regression.py       # encoding tightness/soundness regression suite
│   └── witness_diagnostics.py   # diagnostic checks on encoded instances
├── scripts/                     # Yosys/ABC flows + OpenSTA timing script
├── verification/                # testbench + independent netlist checker
├── results/                     # experiment results (CSV, DOT)
└── figures/y0_schematic.png     # y0 netlist schematic
```

## Reproducing

```bash
pip install -r requirements.txt        # stdlib-only; nothing to install
python3 exact_synthesis/test_regression.py   # needs `kissat` on PATH
```

External tools (not pip-installable):
- **kissat** (SAT solver) — build from
  `https://github.com/arminbiere/kissat` (`./configure && make`), then add
  `build/kissat` to `PATH` or pass `--kissat-path`.
- Yosys (+ ABC) and OpenSTA for the synthesis/timing flows.

The Nangate 45nm liberty files are **not redistributed** in this repository —
place your local copies next to `scripts/` or adjust the paths. See
`problem/gate_library.md` for the gate delay model.

Note: large 6-input exact-synthesis instances (≥ 8 gates) are
computationally heavy (NP-hard); run them with generous timeouts. The
regression suite runs in seconds.

## Status & provenance

- ✅ Verified and included: `SB.v` (original S-box, matches the Dillon
  permutation), `y0_final.v` (123.03 ps, 27 gates, depth 5), and the
  complete `exact_synthesis/` framework (regression suite passes 7/7,
  including UNSAT tightness checks and independent functional
  verification of recovered circuits).
- ⚠️ **Not included — failed verification**: all available y1/y2 final
  netlists implement functions other than the S-box's y1/y2 (numbers in
  the table above). Treat the historical "y1 140.68 ps / y2 126.70 ps"
  claims as unconfirmed until matching netlists are produced.
- ⚠️ **Not included — polarity defect**: the earlier template-search y0
  reference (`y0_doubao.v`-style, 156.83 ps) outputs the complement of y0
  as written.
- [ ] Fill in the `LICENSE` and finalize figures after thesis submission.
