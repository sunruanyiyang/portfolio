# Truth tables

## Bit convention

For an input pattern `m` in `[0, 64)`, input variable `x_k` takes bit `k` of
`m` (`x_k = (m >> k) & 1`), and the value of output `y_b` at pattern `m` is
bit `m` of the 64-bit truth-table integer. This is the little-endian
minterm convention used by `search/truth.py` and the SAT encoder
(`exact_synthesis/encoder/truth_table.py`).

## Dillon permutation (official competition S-box)

From `verification/verify.v` (ground truth). `y = P[x]`, written in hex:

| x   | 00 01 02 03 04 05 06 07 08 09 0a 0b 0c 0d 0e 0f |
|-----|---------------------------------------------------|
| P[x]| 00 36 30 0d 0f 12 35 23 19 3f 2d 34 03 14 29 21 |
| x   | 10 11 12 13 14 15 16 17 18 19 1a 1b 1c 1d 1e 1f |
| P[x]| 3b 24 02 22 0a 08 39 25 3c 13 2a 0e 32 1a 3a 18 |
| x   | 20 21 22 23 24 25 26 27 28 29 2a 2b 2c 2d 2e 2f |
| P[x]| 27 1b 15 11 10 1d 01 3e 2f 28 33 38 07 2b 2c 26 |
| x   | 30 31 32 33 34 35 36 37 38 39 3a 3b 3c 3d 3e 3f |
| P[x]| 1f 0b 04 1c 3d 2e 05 31 09 06 17 20 1e 0c 37 16 |

i.e. `P[0]=0x00, P[1]=0x36, ..., P[63]=0x16`.

## Derived single-output truth tables

`y_b(m) = bit b of P[m]`, packed with the little-endian convention above
(computed from the testbench table):

| output | 64-bit truth table |
|---|---|
| y0 | `0x45D3356F02C1D7D8` |
| y1 | `0xD623B5837E1D12B2` |
| y2 | `0xF67DD1A509822E5A` |
| y3 | `0x313B6BA2ED714718` |
| y4 | `0xD4990CBEF3412B66` |
| y5 | `0x48B0EF8155CBCEC6` |

Cross-checks (all agree):

* `y0 = 0x45D3356F02C1D7D8` matches `search/truth.py`
  (`Y0_TRUTH = 0x45D3356F02C1D7D8`).
* The algebraic-normal-form implementation `rtl/original/SB.v` reproduces
  the permutation for all six outputs (checked by re-simulation).
* `rtl/optimized/y0_final.v` reproduces y0 exactly (checked by
  independent 64-input gate-level simulation).

## ⚠️ Known discrepancy: y1 / y2 netlist files (excluded from this repo)

Every y1/y2 netlist available in the project files implements a function
that is **not** the corresponding bit of this S-box. Independently
re-simulated (gate-level, all 64 patterns):

| file (not included in this repo) | implements | canonical bit |
|---|---|---|
| `y1_FINAL_fixed_best.v` | `0x1EF2BA4B1A8CC3D9` | y1 = `0xD623B5837E1D12B2` |
| `y2_FINAL_fixed_best.v` | `0x0D8D35B8659ADC24` | y2 = `0xF67DD1A509822E5A` |
| `y2_FINAL_full_best.v` | `0x0D8D35B8659ADC24` | y2 = `0xF67DD1A509822E5A` |
| `y2_mapped.v` | `0x243B59A61DACB1B0` | y2 = `0xF67DD1A509822E5A` |

None matches any output bit of the Dillon permutation under any
input-variable permutation or polarity. The header claims of "ABC cec +
64-input Python simulation" on those files are therefore not reproduced by
independent simulation; y1/y2 delay numbers are **not published** in this
repository until netlists that pass verification are produced.

## ⚠️ Known discrepancy: y0 template-search candidate (excluded)

The template-search y0 candidate (the `x2 → x4 → x5` order, 156.83 ps in
`results/y0_best_2_4_5_156.83ps.dot`) outputs the **complement** of y0 as
written: its internal `y0_n` wire computes the positive function and the
final `assign y0 = ~y0_n` adds a spurious inversion (verified by
re-simulation). The file is therefore not included in `rtl/`.
