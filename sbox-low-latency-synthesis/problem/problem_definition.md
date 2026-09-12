# Problem definition

## Task

Synthesize gate-level implementations of the single-output Boolean
functions of a 6-input / 6-output S-box with **minimum critical-path
delay**. The design is mapped to a Nangate 45nm standard-cell library
subset (see `gate_library.md`). Area and gate count are secondary; the
optimization metric is the delay of the slowest path.

This is the classic *delay-optimal exact synthesis* problem for
small Boolean functions: find a circuit over a fixed gate library that
realizes a given truth table and whose critical path is as short as
possible, typically with a tight gate budget.

## Target function: the S-box

The S-box is the official "Dillon permutation" (6×6) used by the
competition testbench in `verification/verify.v`:

```
y = P[x],  x, y ∈ {0..63}
```

with input bits `x0..x5 = x[0..5]` and output bits `y0..y5` the six bits
of `P[x]`. The full table and the six derived single-output truth tables
are listed in `truth_tables.md`.

Each of the six output functions `y0..y5` is a 6-input, single-output
Boolean function (64 minterms) and is synthesized independently.

## Gate library

The synthesis engine uses a fixed set of primitives with fixed delays
(characterization for the study, in picoseconds):

| gate | arity | delay (ps) |
|---|---|---|
| INV | 1 | 22.048 |
| BUF | 1 | 33.557 |
| NAND2 | 2 | 27.886 |
| NOR2 | 2 | 40.650 |
| AND2 | 2 | 40.171 |
| NAND3 | 3 | 34.767 |
| OAI21 | 3 | 32.651 |
| NAND4 | 4 | 44.487 |
| AOI21 | 3 | 51.619 |
| AND3 | 3 | 51.869 |
| OAI22 | 4 | 54.596 |
| XNOR2 | 2 | 57.604 |
| AOI22 | 4 | 57.255 |

These are the fixed delay constants used during development (the SAT delay
encoder and the heuristic search both relied on them). Static timing
analysis of the final netlists is performed with the full Nangate library
via OpenSTA (`scripts/sta.tcl`); the numbers reported in the netlist
headers (e.g. 123.03 ps) are STA results.

## Evaluation flow

1. **Baseline**: synthesize `SB.v` with Yosys + plain ABC
   (`scripts/abc_baseline.ys`).
2. **Heuristic search**: two-layer Shannon decomposition over split
   variable orders (`search/`), each candidate measured through Yosys/ABC.
3. **Template search**: exhaustively compose leaf functions from library
   gate templates (`search/template_search.py`).
4. **Exact synthesis**: encode the existence of a delay-bounded circuit as
   a CNF instance and solve it with the external kissat binary
   (`exact_synthesis/`), then recover the circuit and emit Verilog. A
   regression suite (`exact_synthesis/test_regression.py`) asserts both
   encoding tightness (optimal − 1 gates is UNSAT) and soundness
   (recovered circuits pass independent functional simulation).
5. **ABC delay-oriented deep synthesis**: repeated rebalancing + SAT
   restructuring with a delay target (`scripts/abc_optimize.ys`).
6. **Verification**: 64-input exhaustive simulation (`verification/`), ABC
   CEC, and OpenSTA timing analysis.

## Library redistribution note

The experiments depend on a filtered Nangate 45nm standard-cell library
(`NangateOpenCellLibrary_filtered.lib` locally). The library file is **not
redistributed** in this repository; `gate_library.md` documents the fixed
delay model used by the engine so the results are reproducible with a
matching library.
