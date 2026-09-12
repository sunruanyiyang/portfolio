"""
test_regression.py - REGRESSION SUITE FOR THE CNF/KISSAT SYNTHESIS PIPELINE

Runs the FULL pipeline (encode -> DIMACS -> kissat -> parse -> extract ->
Verilog -> functional verification) against several small Boolean functions
whose optimal gate count under this project's library is known analytically,
so any regression in the encoding shows up as either:

  - a MISSING solution where one must exist (encoding over-constrains), or
  - a WRONG solution (encoding under-constrains / is unsound), or
  - a solution found with FEWER gates than analytically possible (encoding
    is unsound -- e.g. the delay/backward-clause bugs fixed earlier would
    have shown up here), or
  - a solution found with MORE gates than the known optimum, when the
    smaller budget is asserted UNSAT (encoding over-constrains).

Each test case asserts, where applicable:
  1. The gate budget ONE BELOW the known optimum is UNSAT (tightness check --
     confirms the encoding isn't accidentally satisfiable with too few gates,
     which would indicate a soundness bug like the ones fixed earlier in this
     project's history).
  2. The known-optimal gate budget IS SAT, and the recovered circuit:
       - has the claimed gate count,
       - passes structural verification (acyclic, in-range fanins),
       - passes functional verification against the target truth table
         (independent re-simulation, not just trusting the SAT model),
       - round-trips through Verilog generation without error.

Run: python3 test_regression.py
Exit code 0 iff every test passes.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "encoder"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "recover"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "solver"))

from config import RunConfig
from synthesize import search_optimal_delay_for_budget
from generate_verilog import export_circuit_to_file
from verify import verify_circuit_against_truth_table, simulate_circuit_on_minterm
from extract_model import verify_circuit_structure
from truth_table import all_minterms


# ---------------------------------------------------------------------------
# Test case definitions: small functions with analytically known optima.
# ---------------------------------------------------------------------------

@dataclass
class RegressionCase:
    name: str
    num_inputs: int
    truth_table_fn: callable          # (assignment: tuple[int,...]) -> int
    known_optimal_gates: int          # exact optimum (asserted tightly)
    assert_budget_minus_one_unsat: bool = True
    search_upper_gates: int = None    # if optimum uncertain, search up to this and
                                       # just require SOME solution in range;
                                       # known_optimal_gates then means "search from"
    exact_optimum_known: bool = True  # False => don't assert tightness at optimal-1,
                                       # only assert a solution exists by search_upper_gates


def _truth_table_int(num_inputs: int, fn) -> int:
    tt = 0
    for m in all_minterms(num_inputs):
        assignment = tuple((m >> k) & 1 for k in range(num_inputs))
        if fn(assignment):
            tt |= (1 << m)
    return tt


CASES: list[RegressionCase] = [
    RegressionCase(
        name="IDENTITY1 (y = x0)",
        num_inputs=1,
        truth_table_fn=lambda a: a[0],
        known_optimal_gates=0,
        assert_budget_minus_one_unsat=False,  # can't test budget -1
    ),
    RegressionCase(
        name="INV1 (y = NOT x0)",
        num_inputs=1,
        truth_table_fn=lambda a: 1 - a[0],
        known_optimal_gates=1,
    ),
    RegressionCase(
        name="AND2 (y = x0 AND x1)",
        num_inputs=2,
        truth_table_fn=lambda a: a[0] & a[1],
        known_optimal_gates=1,
    ),
    RegressionCase(
        name="NAND2 (y = NOT(x0 AND x1))",
        num_inputs=2,
        truth_table_fn=lambda a: 1 - (a[0] & a[1]),
        known_optimal_gates=1,
    ),
    RegressionCase(
        name="NOR2 (y = NOT(x0 OR x1))",
        num_inputs=2,
        truth_table_fn=lambda a: 1 - (a[0] | a[1]),
        known_optimal_gates=1,
    ),
    RegressionCase(
        name="XNOR2 (y = x0 XNOR x1)",
        num_inputs=2,
        truth_table_fn=lambda a: 1 - (a[0] ^ a[1]),
        known_optimal_gates=1,
    ),
    RegressionCase(
        name="MAJ3 (y = majority(x0,x1,x2))",
        num_inputs=3,
        truth_table_fn=lambda a: 1 if (a[0] + a[1] + a[2]) >= 2 else 0,
        known_optimal_gates=2,       # search starts at 2 (1 is asserted UNSAT below)
        search_upper_gates=5,        # widen search; exact optimum not hand-verified
        exact_optimum_known=False,   # only assert budget=1 UNSAT + some solution found by 5
    ),
]


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def make_config(case: RegressionCase, num_gates: int, work_dir: str) -> RunConfig:
    input_names = tuple(f"x{i}" for i in range(case.num_inputs))
    tt_int = _truth_table_int(case.num_inputs, case.truth_table_fn)
    return RunConfig(
        num_inputs=case.num_inputs,
        target_truth_table_int=tt_int,
        output_name="y",
        input_names=input_names,
        min_gate_budget=num_gates,
        max_gate_budget=num_gates,
        lower_bound_ps=0.0,
        upper_bound_ps=1000.0,   # generous -- delay is not under test here
    )


def run_case(case: RegressionCase, base_work_dir: str, verbose: bool = True) -> tuple[bool, str]:
    """Returns (passed, message)."""
    print(f"\n{'='*70}")
    print(f"CASE: {case.name}")
    print(f"{'='*70}")

    work_dir = os.path.join(base_work_dir, case.name.split()[0])
    os.makedirs(work_dir, exist_ok=True)

    # --- Step 1: tightness check (optimum - 1 must be UNSAT) ---------------
    if case.assert_budget_minus_one_unsat:
        below = case.known_optimal_gates - 1
        if below >= 0:
            config = make_config(case, below, work_dir)
            t0 = time.time()
            result = search_optimal_delay_for_budget(config, below, work_dir, verbose=False)
            elapsed = time.time() - t0
            if result is not None:
                return False, (
                    f"FAIL: expected UNSAT at {below} gates (tightness check), "
                    f"but found a solution with {result['circuit'].num_gates()} gates "
                    f"({elapsed:.2f}s). This means the encoding is UNSOUND -- it is "
                    f"accepting fewer gates than analytically possible for this function."
                )
            print(f"  [OK] {below} gates correctly UNSAT ({elapsed:.2f}s) -- tightness confirmed")

    # --- Step 2: known-optimal (or search-range) budget must be SAT --------
    if case.exact_optimum_known:
        gate_counts_to_try = [case.known_optimal_gates]
    else:
        gate_counts_to_try = list(range(case.known_optimal_gates, case.search_upper_gates + 1))

    found_result = None
    found_at_gates = None
    for num_gates in gate_counts_to_try:
        config = make_config(case, num_gates, work_dir)
        t0 = time.time()
        result = search_optimal_delay_for_budget(config, num_gates, work_dir, verbose=False)
        elapsed = time.time() - t0
        if result is not None:
            found_result = result
            found_at_gates = num_gates
            print(f"  [OK] {num_gates} gates: SAT found ({elapsed:.2f}s)")
            break
        else:
            print(f"  ({num_gates} gates: UNSAT, {elapsed:.2f}s)")

    if found_result is None:
        return False, (
            f"FAIL: no solution found in gate range {gate_counts_to_try} -- "
            f"expected at least one SAT result. This means the encoding is "
            f"OVER-CONSTRAINED -- it is rejecting circuits that should exist."
        )

    if case.exact_optimum_known and found_at_gates != case.known_optimal_gates:
        return False, (
            f"FAIL: expected optimum at {case.known_optimal_gates} gates, "
            f"found at {found_at_gates} instead."
        )

    circuit = found_result["circuit"]

    # --- Step 3: structural verification ------------------------------------
    if not verify_circuit_structure(circuit, case.num_inputs):
        return False, "FAIL: extracted circuit failed structural verification (cycle or out-of-range fanin)."
    print(f"  [OK] structural verification passed")

    # --- Step 4: functional verification (independent re-simulation) -------
    config_for_verify = make_config(case, found_at_gates, work_dir)
    ok = verify_circuit_against_truth_table(
        circuit, config_for_verify.target_truth_table_int, case.num_inputs, verbose=False
    )
    if not ok:
        return False, "FAIL: extracted circuit does NOT match target truth table (SAT model was unsound)."
    print(f"  [OK] functional verification passed (all {1 << case.num_inputs} minterms)")

    # --- Step 5: Verilog generation round-trip ------------------------------
    verilog_path = os.path.join(work_dir, "result.v")
    try:
        export_circuit_to_file(
            circuit, verilog_path, module_name="test_circuit",
            input_names=config_for_verify.input_names, output_name="y",
        )
    except Exception as e:
        return False, f"FAIL: Verilog generation raised an exception: {e}"

    if not os.path.exists(verilog_path) or os.path.getsize(verilog_path) == 0:
        return False, "FAIL: Verilog file was not written or is empty."
    print(f"  [OK] Verilog generated: {verilog_path} ({os.path.getsize(verilog_path)} bytes)")

    return True, f"PASS ({found_at_gates} gates, matches known optimum: {case.exact_optimum_known})"


def main():
    base_work_dir = os.path.join(os.path.dirname(__file__), "regression_work")
    if os.path.exists(base_work_dir):
        shutil.rmtree(base_work_dir)
    os.makedirs(base_work_dir, exist_ok=True)

    results = []
    for case in CASES:
        try:
            passed, message = run_case(case, base_work_dir)
        except Exception as e:
            passed, message = False, f"EXCEPTION: {type(e).__name__}: {e}"
        results.append((case.name, passed, message))

    print(f"\n{'='*70}")
    print("REGRESSION SUITE SUMMARY")
    print(f"{'='*70}")
    all_passed = True
    for name, passed, message in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name:35s} {message}")
        if not passed:
            all_passed = False
    print(f"{'='*70}")

    if all_passed:
        print(f"ALL {len(results)} REGRESSION TESTS PASSED.")
        print("Safe to proceed to the real 6-input y0 optimization search.")
    else:
        num_failed = sum(1 for _, p, _ in results if not p)
        print(f"{num_failed} / {len(results)} TESTS FAILED. Do NOT proceed to the")
        print("real y0 search until these are fixed -- the encoding has a bug.")

    shutil.rmtree(base_work_dir, ignore_errors=True)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
