"""
synthesize.py - TOP-LEVEL CNF-BASED SYNTHESIS DRIVER

Orchestrates the full pipeline for one gate budget:

    Truth table -> encoder/* -> DIMACS CNF -> kissat -> SAT assignment
                -> recover/extract_model.py -> recover/generate_verilog.py

and performs the same binary search over delay bounds as the old PySAT-based
search.py, except each delay hypothesis is now a SEPARATE external kissat
invocation on a fresh DIMACS file (kissat, unlike the old in-process
Cadical103 usage, has no incremental/assumption API -- every run is a fresh
process on a self-contained CNF file; this is the fundamental shape change
this architecture requires).

PERFORMANCE NOTE: structure/symmetry/function clauses do not depend on the
delay bound, so they're encoded ONCE per gate budget and cached as raw
DIMACS clause TEXT (not re-run through the Python encoders on every binary
search step, and not held as a giant Python list either -- just a body file
on disk). Each delay-bound test then only re-encodes the (much smaller)
delay clause set and concatenates it with the cached static body to produce
that test's complete CNF file.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "encoder"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "recover"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "solver"))

from config import RunConfig, level_to_ps, ps_to_level
from variables import VariablePool, allocate_structure_variables, allocate_delay_variables
from structure_encoder import encode_structure_constraints
from symmetry_breaking import encode_symmetry_breaking_constraints
from function_encoder import encode_function_constraints
from delay_encoder import encode_delay_constraints, compute_reachable_levels
from dimacs_writer import DimacsWriter

from extract_model import extract_circuit_from_model, verify_circuit_structure, circuit_to_netlist_text
from generate_verilog import export_circuit_to_file
from verify import verify_circuit_against_truth_table

from run_kissat import run_kissat, run_kissat_portfolio, find_kissat_binary


@dataclass
class StaticCNFCache:
    """Cached DIMACS text for the delay-independent clause set (structure +
    symmetry + function), encoded exactly once per gate budget."""
    body_path: str
    num_clauses: int
    max_var: int

    def cleanup(self):
        if os.path.exists(self.body_path):
            os.remove(self.body_path)


def build_static_cache(pool, struct_vars, target_truth_table_int, work_dir: str, verbose: bool = True) -> StaticCNFCache:
    """
    Encode structure+symmetry+function clauses (delay-independent) exactly
    once per gate budget, and persist them as a raw DIMACS clause-text body
    file that survives the whole binary search over delay bounds.
    """
    writer = DimacsWriter(dir=work_dir)
    t0 = time.time()
    encode_structure_constraints(pool, writer.add_clause, struct_vars)
    encode_symmetry_breaking_constraints(pool, writer.add_clause, struct_vars)
    encode_function_constraints(pool, writer.add_clause, struct_vars, target_truth_table_int)
    if verbose:
        print(f"  Static clauses (structure+symmetry+function): {writer.num_clauses():,} "
              f"encoded in {time.time() - t0:.2f}s")

    num_clauses = writer.num_clauses()
    max_var = writer.max_var_seen()
    tmp_path = writer._tmp_path
    # Close the writer's temp file handle explicitly before moving it --
    # renaming a still-open file handle is unsafe on some platforms.
    writer._tmp_file.close()
    writer._finalized = True  # prevents __del__ from double-closing/removing

    cache_path = os.path.join(work_dir, "static_body.tmp")
    os.replace(tmp_path, cache_path)

    return StaticCNFCache(body_path=cache_path, num_clauses=num_clauses, max_var=max_var)


def build_delay_cnf(
    pool, struct_vars, delay_vars, mid_level: int, reachable_levels: list[int],
    static_cache: StaticCNFCache, output_cnf_path: str,
) -> int:
    """
    Build the complete CNF file for one delay hypothesis: header + cached
    static body + freshly-encoded delay clauses. Returns the delay clause
    count.

    IMPORTANT: the header's variable count MUST be read from `pool` AFTER
    encode_delay_constraints() has run, not before -- delay encoding
    lazily allocates additional "ready" auxiliary variables via
    pool.fresh_var() as it goes, so any variable count captured earlier
    would undercount and produce a CNF header that Kissat rejects
    ("maximum variable index exceeded").
    """
    # Temp body must sit on the same filesystem as the output .cnf (os.replace
    # below would otherwise fail with EXDEV when /tmp is a different mount).
    delay_writer = DimacsWriter(dir=os.path.dirname(output_cnf_path))
    encode_delay_constraints(pool, delay_writer.add_clause, struct_vars, delay_vars, mid_level, reachable_levels)
    num_delay_clauses = delay_writer.num_clauses()
    num_vars = pool.num_vars()  # read AFTER encoding, not before

    delay_writer._tmp_file.close()
    delay_writer._finalized = True

    total_clauses = static_cache.num_clauses + num_delay_clauses

    with open(output_cnf_path, "w") as out:
        out.write(f"c CNF for gate-budget/delay-hypothesis test\n")
        out.write(f"p cnf {num_vars} {total_clauses}\n")
        with open(static_cache.body_path, "r") as sf:
            out.write(sf.read())
        with open(delay_writer._tmp_path, "r") as df:
            out.write(df.read())

    os.remove(delay_writer._tmp_path)
    return num_delay_clauses


def search_optimal_delay_for_budget(
    config: RunConfig, num_gates: int, work_dir: str,
    kissat_path: Optional[str] = None, kissat_timeout_s: Optional[float] = None,
    verbose: bool = True, num_workers: int = 1,
) -> Optional[dict]:
    if verbose:
        print(f"\n--- Searching for {num_gates}-gate circuit (CNF/Kissat pipeline) ---")

    os.makedirs(work_dir, exist_ok=True)

    pool = VariablePool()
    struct_vars = allocate_structure_variables(pool, num_gates, config.num_inputs, config.max_gate_arity)
    delay_vars = allocate_delay_variables(pool, num_gates, config.num_inputs, config.max_delay_levels)

    lower_bound_level = config.lower_bound_level()
    upper_bound_level = config.upper_bound_level()
    reachable_levels = compute_reachable_levels(num_gates, upper_bound_level)
    if verbose:
        print(f"  Reachable delay levels: {len(reachable_levels)} "
              f"(vs {upper_bound_level - lower_bound_level + 1} dense levels)")

    num_nodes = config.num_inputs + num_gates
    for n in range(num_nodes):
        for level in reachable_levels:
            if level not in delay_vars.at_vars[n]:
                delay_vars.at_vars[n][level] = pool.fresh_var(f"AT[node_{n}][level_{level}]")

    static_cache = build_static_cache(pool, struct_vars, config.target_truth_table_int, work_dir, verbose)

    lower_level, upper_level = lower_bound_level, upper_bound_level
    best_delay_level = None
    best_model = None

    try:
        while lower_level <= upper_level:
            mid_level = (lower_level + upper_level) // 2
            mid_ps = level_to_ps(mid_level)

            num_vars_before_delay = pool.num_vars()
            cnf_path = os.path.join(work_dir, f"g{num_gates}_lvl{mid_level}.cnf")

            t0 = time.time()
            num_delay_clauses = build_delay_cnf(
                pool, struct_vars, delay_vars, mid_level, reachable_levels,
                static_cache, cnf_path,
            )
            if verbose:
                print(f"  Testing delay level {mid_level} ({mid_ps:.3f} ps): "
                      f"{num_delay_clauses:,} delay clauses, "
                      f"CNF written in {time.time() - t0:.2f}s -> {cnf_path}")

            if verbose:
                mode_desc = f"{num_workers} parallel workers (portfolio)" if num_workers > 1 else "single worker"
                print(f"    (kissat running -- {mode_desc}; this can take a long time on hard instances)")
            if num_workers > 1:
                result = run_kissat_portfolio(cnf_path, kissat_path=kissat_path,
                                               timeout_s=kissat_timeout_s, num_workers=num_workers)
            else:
                result = run_kissat(cnf_path, kissat_path=kissat_path, timeout_s=kissat_timeout_s, stream_output=verbose)
            if verbose:
                status = "SAT" if result.satisfiable else ("UNSAT" if result.satisfiable is False else "TIMEOUT/ERROR")
                print(f"    kissat: {status}  ({result.solve_time_s:.2f}s)")

            if result.satisfiable is None:
                raise RuntimeError(f"kissat did not return a conclusive result for {cnf_path} "
                                    f"(timeout or error). Raw output tail:\n{result.raw_stdout[-500:]}")

            if result.satisfiable:
                best_delay_level = mid_level
                best_model = result.model
                upper_level = mid_level - 1
            else:
                lower_level = mid_level + 1

            os.remove(cnf_path)
    finally:
        static_cache.cleanup()

    if best_delay_level is None:
        if verbose:
            print(f"  No feasible {num_gates}-gate circuit found within delay bounds.")
        return None

    circuit = extract_circuit_from_model(struct_vars, best_model)
    best_delay_ps = level_to_ps(best_delay_level)

    if verbose:
        print(f"  Found solution: {circuit.num_gates()} gates, "
              f"delay {best_delay_ps:.3f} ps (level {best_delay_level})")

    return {
        "circuit": circuit,
        "achieved_delay_ps": best_delay_ps,
        "achieved_delay_level": best_delay_level,
        "gate_budget": num_gates,
    }


def main():
    parser = argparse.ArgumentParser(description="CNF/Kissat-based exact logic synthesis.")
    parser.add_argument("--min-gates", type=int, default=1)
    parser.add_argument("--max-gates", type=int, default=12)
    parser.add_argument("--lower-bound-ps", type=float, default=0.0)
    parser.add_argument("--upper-bound-ps", type=float, default=600.0)
    parser.add_argument("--output-file", type=str, default="synthesized_y0.v")
    parser.add_argument("--work-dir", type=str, default="./cnf_work")
    parser.add_argument("--kissat-path", type=str, default=None)
    parser.add_argument("--kissat-timeout-s", type=float, default=None)
    parser.add_argument("--num-workers", type=int, default=1,
                         help="Run this many parallel kissat instances per delay test, each with a "
                              "different random seed, and use whichever finishes first. Safe speedup "
                              "on hard instances (no encoding changes) since SAT solve time has high "
                              "variance across seeds. Default 1 (single worker, no parallelism).")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    verbose = not args.quiet

    find_kissat_binary(args.kissat_path)  # fail fast with a clear message if missing

    config = RunConfig(
        min_gate_budget=args.min_gates,
        max_gate_budget=args.max_gates,
        lower_bound_ps=args.lower_bound_ps,
        upper_bound_ps=args.upper_bound_ps,
    )

    for num_gates in range(config.min_gate_budget, config.max_gate_budget + 1):
        result = search_optimal_delay_for_budget(
            config, num_gates, args.work_dir,
            kissat_path=args.kissat_path, kissat_timeout_s=args.kissat_timeout_s,
            verbose=verbose, num_workers=args.num_workers,
        )
        if result is not None:
            circuit = result["circuit"]
            if not verify_circuit_structure(circuit, config.num_inputs):
                print("ERROR: circuit structure verification failed.")
                return 1

            export_circuit_to_file(
                circuit, args.output_file, module_name="synthesized_y0",
                input_names=config.input_names, output_name=config.output_name,
            )
            ok = verify_circuit_against_truth_table(circuit, config.target_truth_table_int, config.num_inputs)
            print(f"\n{'='*70}")
            print(f"Gates: {circuit.num_gates()}  Delay: {result['achieved_delay_ps']:.3f} ps")
            print(f"Functional verification: {'PASS' if ok else 'FAIL'}")
            print(f"Verilog written to: {args.output_file}")
            print(f"{'='*70}")
            return 0 if ok else 1

    print("No feasible circuit found within the specified search space.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
