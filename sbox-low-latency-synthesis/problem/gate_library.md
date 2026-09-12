# Gate library

## Fixed delay model (used by the synthesis engine)

The heuristic search and the (not-included) SAT delay encoder use fixed
per-gate delays, characterized for this study. The same constants are
documented here for reference:

| gate | arity | function | delay (ps) |
|---|---|---|---|
| INV | 1 | `~A` | 22.048 |
| BUF | 1 | `A` | 33.557 |
| NAND2 | 2 | `~(A1 & A2)` | 27.886 |
| NOR2 | 2 | `~(A1 \| A2)` | 40.650 |
| AND2 | 2 | `A1 & A2` | 40.171 |
| NAND3 | 3 | `~(A1 & A2 & A3)` | 34.767 |
| OAI21 | 3 | `~((A1 \| A2) & B1)` | 32.651 |
| NAND4 | 4 | `~(A1 & A2 & A3 & A4)` | 44.487 |
| AOI21 | 3 | `~((A1 & A2) \| B1)` | 51.619 |
| AND3 | 3 | `A1 & A2 & A3` | 51.869 |
| OAI22 | 4 | `~((A1 \| A2) & (B1 \| B2))` | 54.596 |
| XNOR2 | 2 | `~(A1 ^ A2)` | 57.604 |
| AOI22 | 4 | `~((A1 & A2) \| (B1 & B2))` | 57.255 |

## Cell semantics in the shipped netlists

The final netlists use Nangate 45nm `_X1` cells (and `_X2/_X4/_X16/_X32`
drive variants with identical logic). Two pin conventions appear:

For the `A, B1, B2` convention (used by `rtl/optimized/y0_final.v`):

| cell | function |
|---|---|
| INV_X1 | `ZN = ~A` |
| NAND2_X1 | `ZN = ~(A1 & A2)` |
| NAND3_X1 | `ZN = ~(A1 & A2 & A3)` |
| NAND4_X1 | `ZN = ~(A1 & A2 & A3 & A4)` |
| NOR2_X1 | `ZN = ~(A1 \| A2)` |
| AND2_X1 | `ZN = A1 & A2` |
| OAI21_X1 | `ZN = ~(A & (B1 \| B2))` |
| AOI21_X1 | `ZN = ~(A \| (B1 & B2))` |
| OAI22_X1 | `ZN = ~((A1 \| A2) & (B1 \| B2))` |
| AOI22_X1 | `ZN = ~((A1 & A2) \| (B1 & B2))` |

(The older fixed-delay netlists use the `A1, A2, B1` convention with
output pin `Y`; there `OAI21 = ~((A1|A2) & B1)` and
`AOI21 = ~((A1&A2) | B1)`.)

## Library redistribution note

The experiments depend on a filtered Nangate 45nm standard-cell library
(`NangateOpenCellLibrary_filtered.lib` locally) and, for STA, the typical
liberty (`NangateOpenCellLibrary_typical.lib`). These files are **not
redistributed** in this repository. To reproduce the timing numbers, place
your local copies next to `scripts/` or adjust the paths in
`scripts/abc_optimize.ys` and `scripts/sta.tcl`.

The filtered library contains `_X1/_X2/_X4` drive variants of: `AND2`,
`AND3`, `AOI21`, `AOI22`, `INV`, `NAND2`, `NAND3`, `NAND4`, `NOR2`,
`OAI21`, `OAI22` (34 cells total). Note that the library tables' worst-case
rise/fall delays (at the characterized slew/load corner) are several times
larger than the fixed delays above — the fixed delays are the nominal
single-point values used by the synthesis engine, while the header delay
claims come from OpenSTA on the full library.
