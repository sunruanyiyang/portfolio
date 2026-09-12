"""
witness_diagnostics.py - VALIDATE THE ENCODER AGAINST A KNOWN-GOOD WITNESS

Parses the known y0 implementation, builds the COMPLETE SAT variable
assignment that circuit implies -- including every Tseitin AUXILIARY
variable the encoders introduce (AMO/commander vars for gate-type
selection, mux vars for function encoding, fanin_ready vars for delay
encoding), not just the "meaningful" variables -- and checks that
assignment against each clause family independently:

  1. Structure + Function only (no delay)
  2. Structure + Delay only (using the witness's own real topology/timing,
     no function/signal constraints)
  3. Full encoding (structure + symmetry + function + delay together)

WHY AUXILIARY VARIABLES MATTER
================================
An earlier version of this checker left every Tseitin auxiliary variable
(amo_s_i, cmd_i, mux[...], fanin_ready[...]) at its default value (False)
since we never "meant" those variables to represent anything about the
witness circuit directly. That was wrong: these variables are NOT free --
the encoder's clauses require them to take specific values once the
"real" variables (gate type, fanin, signal, arrival time) are fixed. Every
violation the first version reported was exactly this kind of gap, not a
genuine encoder bug. This version derives correct values for all of them:

  - amo_s_i / cmd_i (commander encoding for gate-type-onehot): computed
    directly from the deterministic, verified-empirically slot layout of
    encode_gate_type_onehot's fresh_var() allocation order (see
    compute_gate_type_onehot_aux_values below).
  - mux[g][p][m]: uniquely named per (gate, position, minterm), so looked
    up directly by parsing descriptions, and set to the ACTUAL signal
    value of whichever node is really bound to that fanin position.
  - fanin_ready[g][p][pred]: same idea, set to whether the real bound
    source's arrival time is <= pred.

This does NOT invoke Kissat -- clause satisfaction is checked directly in
Python against the concrete witness assignment.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "encoder"))

from config import ps_to_level, level_to_ps
from variables import VariablePool, allocate_structure_variables, allocate_delay_variables
from gate_library import GateType, GATE_LIBRARY, GATE_TYPES_ORDERED, delay_level_of
from structure_encoder import encode_structure_constraints
from symmetry_breaking import encode_symmetry_breaking_constraints
from function_encoder import encode_function_constraints
from delay_encoder import encode_delay_constraints, compute_reachable_levels
from truth_table import all_minterms, target_output_bit, TARGET_TRUTH_TABLE_INT


# ---------------------------------------------------------------------------
# Netlist parsing
# ---------------------------------------------------------------------------

OUTPUT_PIN_CANDIDATES = ["Y", "ZN", "Z", "Q"]

# Multiple netlists/tools name pins differently for the SAME function.
# Keyed by (cell_base, frozenset of actual input pin names present) so the
# correct mapping is picked per-instance rather than assumed globally.
# Verified empirically for the "A, B1, B2" convention by brute-force testing
# every permutation against the target truth table stated in the netlist's
# own header comment -- only [B1, B2, A] (OR-pair, then AND-input) reproduces
# it, matching the real NanGate45 OAI21_X1/AOI21_X1 pin semantics.
PIN_ORDER_VARIANTS = {
    "INV": {frozenset(["A"]): ["A"]},
    "BUF": {frozenset(["A"]): ["A"]},
    "NAND2": {frozenset(["A1", "A2"]): ["A1", "A2"]},
    "NOR2": {frozenset(["A1", "A2"]): ["A1", "A2"]},
    "AND2": {frozenset(["A1", "A2"]): ["A1", "A2"]},
    "XNOR2": {frozenset(["A1", "A2"]): ["A1", "A2"]},
    "NAND3": {frozenset(["A1", "A2", "A3"]): ["A1", "A2", "A3"]},
    "AND3": {frozenset(["A1", "A2", "A3"]): ["A1", "A2", "A3"]},
    "NAND4": {frozenset(["A1", "A2", "A3", "A4"]): ["A1", "A2", "A3", "A4"]},
    "OAI21": {
        frozenset(["A1", "A2", "B1"]): ["A1", "A2", "B1"],   # simplified/custom convention
        frozenset(["A", "B1", "B2"]): ["B1", "B2", "A"],      # real NanGate45 convention
    },
    "AOI21": {
        frozenset(["A1", "A2", "B1"]): ["A1", "A2", "B1"],
        frozenset(["A", "B1", "B2"]): ["B1", "B2", "A"],
    },
    "OAI22": {frozenset(["A1", "A2", "B1", "B2"]): ["A1", "A2", "B1", "B2"]},
    "AOI22": {frozenset(["A1", "A2", "B1", "B2"]): ["A1", "A2", "B1", "B2"]},
}


def resolve_pin_order(cell_base: str, pins: dict) -> list[str]:
    """Pick the correct pin-order mapping for this specific gate instance
    based on which input pin names are actually present, rather than
    assuming one fixed convention for the whole file."""
    if cell_base not in PIN_ORDER_VARIANTS:
        raise ValueError(f"Unknown cell base '{cell_base}' -- no pin-order mapping registered.")
    input_pin_names = frozenset(p for p in pins.keys() if p not in OUTPUT_PIN_CANDIDATES)
    variants = PIN_ORDER_VARIANTS[cell_base]
    if input_pin_names not in variants:
        raise ValueError(
            f"Cell '{cell_base}' has unrecognized pin set {sorted(input_pin_names)}; "
            f"known conventions: {[sorted(k) for k in variants.keys()]}"
        )
    return variants[input_pin_names]


@dataclass
class ParsedGate:
    instance_name: str
    cell_base: str
    pins: dict
    output_signal: str


def parse_netlist(path: str):
    with open(path) as f:
        text = f.read()
    gate_pattern = re.compile(
        r"(\w+)\s+(\w+)\s*\(\s*(\.\w+\([^)]*\)(?:\s*,\s*\.\w+\([^)]*\))*)\s*\)\s*;"
    )
    pin_pattern = re.compile(r"\.(\w+)\(([^)]*)\)")
    gates: list[ParsedGate] = []
    for m in gate_pattern.finditer(text):
        cell_type_full, instance_name, pin_block = m.groups()
        cell_base = re.sub(r"_X\d+$", "", cell_type_full)
        pins, output_signal = {}, None
        for pm in pin_pattern.finditer(pin_block):
            pin_name, sig = pm.group(1), pm.group(2).strip()
            pins[pin_name] = sig
        for candidate in OUTPUT_PIN_CANDIDATES:
            if candidate in pins:
                output_signal = pins[candidate]
                break
        if output_signal is None:
            continue
        gates.append(ParsedGate(instance_name, cell_base, pins, output_signal))
    return gates


def build_node_graph(gates: list[ParsedGate], num_inputs: int, input_bus_name: str = "x"):
    wire_to_node = {f"{input_bus_name}[{i}]": i for i in range(num_inputs)}
    node_gate_type: dict[int, GateType] = {}
    node_fanins: dict[int, list[int]] = {}
    next_node = num_inputs
    output_node = None
    for gate in gates:
        node_idx = next_node
        next_node += 1
        gate_type = GateType[gate.cell_base]
        pin_order = resolve_pin_order(gate.cell_base, gate.pins)
        fanins = []
        for pin in pin_order:
            sig = gate.pins[pin]
            if sig not in wire_to_node:
                raise ValueError(f"Gate {gate.instance_name}: signal '{sig}' used before defined.")
            fanins.append(wire_to_node[sig])
        node_gate_type[node_idx] = gate_type
        node_fanins[node_idx] = fanins
        wire_to_node[gate.output_signal] = node_idx
        output_node = node_idx
    num_gates = next_node - num_inputs
    return node_gate_type, node_fanins, output_node, num_gates


def simulate_all_signals(node_gate_type, node_fanins, num_inputs: int, num_gates: int):
    num_nodes = num_inputs + num_gates
    signal_values: dict[int, dict[int, int]] = {n: {} for n in range(num_nodes)}
    for m in all_minterms(num_inputs):
        for i in range(num_inputs):
            signal_values[i][m] = (m >> i) & 1
        for node_idx in range(num_inputs, num_nodes):
            gt = node_gate_type[node_idx]
            spec = GATE_LIBRARY[gt]
            fanin_vals = [signal_values[f][m] for f in node_fanins[node_idx]]
            signal_values[node_idx][m] = spec.evaluate(fanin_vals)
    return signal_values


def compute_arrival_levels(node_gate_type, node_fanins, num_inputs: int, num_gates: int):
    num_nodes = num_inputs + num_gates
    arrival: dict[int, int] = {i: 0 for i in range(num_inputs)}
    for node_idx in range(num_inputs, num_nodes):
        gt = node_gate_type[node_idx]
        d = delay_level_of(gt)
        fanin_arrivals = [arrival[f] for f in node_fanins[node_idx]]
        arrival[node_idx] = max(fanin_arrivals, default=0) + d
    return arrival


# ---------------------------------------------------------------------------
# Auxiliary-variable value derivation (the actual fix vs. the earlier version)
# ---------------------------------------------------------------------------

def compute_gate_type_onehot_aux_values(
    node_gate_type: dict, num_inputs: int, num_gates: int,
    base_var_before_encoding: int, num_gate_type_options: int, threshold: int = 6,
) -> dict[int, bool]:
    """
    Directly computes correct values for the amo_s_i / cmd_i auxiliary
    variables that encode_gate_type_onehot allocates, using the verified
    empirical fact that they form one contiguous, identically-structured
    block of variables per gate (see module docstring). For num_gate_type_
    options=14, threshold=6: groups are sized [6, 6, 2], giving a fixed
    15-variable-per-gate layout:

        0: cmd_0 | 1-5: group0 amo_s_0..4 | 6: cmd_1 | 7-11: group1 amo_s_0..4
        | 12: cmd_2 (group2 has 2 members -> no aux) | 13-14: top-level amo_s_0..1
    """
    values: dict[int, bool] = {}

    group_sizes, remaining = [], num_gate_type_options
    while remaining > 0:
        group_sizes.append(min(threshold, remaining))
        remaining -= min(threshold, remaining)
    num_groups = len(group_sizes)
    group_starts, acc = [], 0
    for size in group_sizes:
        group_starts.append(acc)
        acc += size

    group_amo_slot_counts = [(size - 1) if size > 2 else 0 for size in group_sizes]
    top_amo_count = (num_groups - 1) if num_groups > 2 else 0
    slots_per_gate = sum(1 + c for c in group_amo_slot_counts) + top_amo_count

    for gate_index in range(num_gates):
        g = num_inputs + gate_index
        k = int(node_gate_type[g])  # GateType's own int value IS the canonical index

        group_idx = local_idx = None
        for gi, start in enumerate(group_starts):
            if start <= k < start + group_sizes[gi]:
                group_idx, local_idx = gi, k - start
                break
        assert group_idx is not None

        gate_base = base_var_before_encoding + gate_index * slots_per_gate
        offset = 0
        for gi, size in enumerate(group_sizes):
            cmd_var = gate_base + offset + 1
            values[cmd_var] = (gi == group_idx)
            offset += 1
            amo_count = group_amo_slot_counts[gi]
            if gi == group_idx and amo_count > 0:
                for j in range(amo_count):
                    values[gate_base + offset + j + 1] = (local_idx <= j)
            offset += amo_count
        for j in range(top_amo_count):
            values[gate_base + offset + j + 1] = (group_idx <= j)

    return values, slots_per_gate


def compute_effective_fanins(node_fanins: dict, struct_vars, num_inputs: int, num_gates: int) -> dict:
    """
    Returns, for every gate node, the FULL per-position fanin binding
    actually written into its binary fanin bits -- including positions
    beyond the gate's true arity, which are padded to node 0 purely to
    satisfy the "< g" range constraint. This padding value (0) refers to a
    REAL node (primary input x0), so function_encoder's per-position mux
    consistency clauses (which are allocated for ALL positions regardless
    of arity -- only the later Tseitin truth-table clauses are arity-
    limited) are genuinely binding even for "unused" positions. Any witness
    construction that skips them is incomplete, not the encoder being buggy.
    """
    effective = {}
    for gate_index in range(num_gates):
        g = num_inputs + gate_index
        actual = node_fanins[g]
        num_positions = len(struct_vars.fanin_binary_vars[g])
        effective[g] = [actual[p] if p < len(actual) else 0 for p in range(num_positions)]
    return effective


def compute_mux_and_ready_values(pool, effective_fanins: dict, arrival: dict, signal_values: dict, num_inputs: int):
    """mux[...] and fanin_ready[...] are uniquely named -- look up directly.
    Uses the FULL effective (arity-padded) fanin binding, since positions
    beyond a gate's true arity are still bound to a real node (0) and are
    still constrained by the encoder -- see compute_effective_fanins."""
    values: dict[int, bool] = {}
    mux_re = re.compile(r"^mux\[g(\d+)\]\[p(\d+)\]\[m(\d+)\]$")
    ready_re = re.compile(r"^fanin_ready\[g(\d+)\]\[p(\d+)\]\[pred(\d+)\]$")

    for var_id, desc in pool.all_descriptions().items():
        m = mux_re.match(desc)
        if m:
            gate_index, p, minterm = int(m.group(1)), int(m.group(2)), int(m.group(3))
            fanins = effective_fanins[num_inputs + gate_index]
            if p < len(fanins):
                values[var_id] = bool(signal_values[fanins[p]][minterm])
            continue
        m2 = ready_re.match(desc)
        if m2:
            gate_index, p, pred = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
            fanins = effective_fanins[num_inputs + gate_index]
            if p < len(fanins):
                values[var_id] = bool(arrival[fanins[p]] <= pred)
            continue
    return values


def build_witness_assignment(
    pool, struct_vars, delay_vars, node_gate_type, node_fanins, output_node,
    num_inputs: int, num_gates: int, signal_values, arrival, reachable_levels,
    aux_base_var: int, num_gate_type_options: int,
) -> dict[int, bool]:
    assignment: dict[int, bool] = {}
    num_nodes = num_inputs + num_gates

    # Gate type + unused
    for gate_index in range(num_gates):
        g = num_inputs + gate_index
        actual_gt = node_gate_type[g]
        for gt, var in struct_vars.gate_type_vars[g].items():
            assignment[var] = (gt == int(actual_gt))
        assignment[struct_vars.unused_vars[g]] = False

    # Fanin binary bits
    for gate_index in range(num_gates):
        g = num_inputs + gate_index
        actual_fanins = node_fanins[g]
        for p in range(len(struct_vars.fanin_binary_vars[g])):
            value = actual_fanins[p] if p < len(actual_fanins) else 0
            for i, bv in enumerate(struct_vars.fanin_binary_vars[g][p]):
                assignment[bv] = bool((value >> i) & 1)

    # Output binary encoding
    for i, bv in enumerate(struct_vars.output_binary_vars[i] for i in range(struct_vars.num_output_bits)):
        assignment[bv] = bool((output_node >> i) & 1)

    # Signal variables
    for n in range(num_nodes):
        for m in all_minterms(num_inputs):
            assignment[struct_vars.signal_vars[n][m]] = bool(signal_values[n][m])

    # AT delay variables
    for n in range(num_nodes):
        for level in reachable_levels:
            if level in delay_vars.at_vars[n]:
                assignment[delay_vars.at_vars[n][level]] = (arrival[n] <= level)

    # AMO/commander auxiliary variables (the actual fix)
    aux_values, slots_per_gate = compute_gate_type_onehot_aux_values(
        node_gate_type, num_inputs, num_gates, aux_base_var, num_gate_type_options
    )
    assignment.update(aux_values)

    # mux / fanin_ready auxiliary variables (computed after function/delay
    # encoders have run, via the caller -- see main())
    return assignment


def eval_literal(assignment: dict[int, bool], lit: int) -> bool:
    var = abs(lit)
    val = assignment.get(var, False)
    return val if lit > 0 else (not val)


def check_clauses(clauses, assignment, max_report=15):
    violations = []
    for clause in clauses:
        if not any(eval_literal(assignment, lit) for lit in clause):
            violations.append(clause)
            if len(violations) >= max_report:
                break
    return violations


def describe_clause(clause, pool):
    parts = []
    for lit in clause:
        var = abs(lit)
        desc = pool.describe(var) or f"var{var}"
        parts.append(f"{'' if lit > 0 else 'NOT '}{desc}")
    return " OR ".join(parts)


def main():
    netlist_path = sys.argv[1] if len(sys.argv) > 1 else "/mnt/user-data/uploads/y0_FINAL_best_delay_v2.v"
    num_inputs = 6

    print("=" * 70)
    print(f"Witness Diagnostics: {netlist_path}")
    print("=" * 70)

    gates = parse_netlist(netlist_path)
    node_gate_type, node_fanins, output_node, num_gates = build_node_graph(gates, num_inputs)
    print(f"Parsed {num_gates} gates (nodes {num_inputs}..{num_inputs+num_gates-1}), output_node={output_node}")
    if num_gates != 24:
        print(f"NOTE: witness has {num_gates} gates, not 24 as described. Proceeding anyway --")
        print(f"this is the only concrete witness available and every gate type it uses")
        print(f"is covered by the current 13-gate library.")

    signal_values = simulate_all_signals(node_gate_type, node_fanins, num_inputs, num_gates)
    arrival = compute_arrival_levels(node_gate_type, node_fanins, num_inputs, num_gates)
    critical_level = arrival[output_node]
    critical_ps = level_to_ps(critical_level)
    print(f"Computed critical-path delay: {critical_ps:.3f} ps (level {critical_level})")

    mismatches = sum(
        1 for m in all_minterms(num_inputs)
        if signal_values[output_node][m] != target_output_bit(m, TARGET_TRUTH_TABLE_INT)
    )
    if mismatches:
        print(f"FATAL: witness does not implement y0 -- {mismatches}/64 minterms wrong.")
        return 1
    print(f"Functional check: witness correctly implements y0 on all 64 minterms.\n")

    pool = VariablePool()
    struct_vars = allocate_structure_variables(pool, num_gates, num_inputs, 4)
    delay_vars = allocate_delay_variables(pool, num_gates, num_inputs, 10_000_000)

    reachable_levels = compute_reachable_levels(num_gates, critical_level + 1)
    num_nodes = num_inputs + num_gates
    for n in range(num_nodes):
        for level in reachable_levels:
            if level not in delay_vars.at_vars[n]:
                delay_vars.at_vars[n][level] = pool.fresh_var(f"AT[node_{n}][level_{level}]")

    aux_base_var = pool.num_vars()  # right before encode_structure_constraints runs
    num_gate_type_options = len(GATE_TYPES_ORDERED) + 1  # + unused

    struct_clauses: list = []
    encode_structure_constraints(pool, struct_clauses.append, struct_vars)

    function_clauses: list = []
    encode_function_constraints(pool, function_clauses.append, struct_vars, TARGET_TRUTH_TABLE_INT)

    delay_clauses: list = []
    encode_delay_constraints(pool, delay_clauses.append, struct_vars, delay_vars, critical_level, reachable_levels)

    symmetry_clauses: list = []
    encode_symmetry_breaking_constraints(pool, symmetry_clauses.append, struct_vars)

    assignment = build_witness_assignment(
        pool, struct_vars, delay_vars, node_gate_type, node_fanins, output_node,
        num_inputs, num_gates, signal_values, arrival, reachable_levels,
        aux_base_var, num_gate_type_options,
    )
    # mux / fanin_ready values, now that the encoders have run and allocated them
    effective_fanins = compute_effective_fanins(node_fanins, struct_vars, num_inputs, num_gates)
    assignment.update(compute_mux_and_ready_values(pool, effective_fanins, arrival, signal_values, num_inputs))

    all_passed = True

    print("-" * 70)
    print("MODE 1: Structure + Function only (no delay)")
    print("-" * 70)
    sv = check_clauses(struct_clauses, assignment)
    fv = check_clauses(function_clauses, assignment)
    print(f"  Structure clauses: {len(struct_clauses):,}  violations: {len(sv)}")
    print(f"  Function clauses:  {len(function_clauses):,}  violations: {len(fv)}")
    if sv or fv:
        all_passed = False
        for v in sv[:5]: print(f"    [STRUCTURE VIOLATION] {describe_clause(v, pool)}")
        for v in fv[:5]: print(f"    [FUNCTION VIOLATION]  {describe_clause(v, pool)}")
    else:
        print("  PASS")
    print()

    print("-" * 70)
    print(f"MODE 2: Structure + Delay only, at witness's critical level ({critical_ps:.3f} ps)")
    print("-" * 70)
    sv2 = check_clauses(struct_clauses, assignment)
    dv = check_clauses(delay_clauses, assignment)
    print(f"  Structure clauses: {len(struct_clauses):,}  violations: {len(sv2)}")
    print(f"  Delay clauses:     {len(delay_clauses):,}  violations: {len(dv)}")
    if sv2 or dv:
        all_passed = False
        for v in sv2[:5]: print(f"    [STRUCTURE VIOLATION] {describe_clause(v, pool)}")
        for v in dv[:5]: print(f"    [DELAY VIOLATION]     {describe_clause(v, pool)}")
    else:
        print("  PASS")
    print()

    print("-" * 70)
    print("MODE 3: Full encoding (structure + symmetry + function + delay)")
    print("-" * 70)
    symv = check_clauses(symmetry_clauses, assignment)
    print(f"  Structure clauses: {len(struct_clauses):,}  violations: {len(sv2)}")
    print(f"  Symmetry clauses:  {len(symmetry_clauses):,}  violations: {len(symv)}")
    print(f"  Function clauses:  {len(function_clauses):,}  violations: {len(fv)}")
    print(f"  Delay clauses:     {len(delay_clauses):,}  violations: {len(dv)}")
    full_pass = not (sv2 or symv or fv or dv)
    print("  PASS" if full_pass else "  FAIL")
    if not full_pass:
        all_passed = False
    print()

    print("=" * 70)
    if all_passed:
        print("ALL THREE DIAGNOSTIC MODES PASSED.")
        print(f"The known {num_gates}-gate / {critical_ps:.3f} ps implementation satisfies")
        print("every constraint family independently. Safe to trust the SAT search.")
    else:
        print("AT LEAST ONE MODE FAILED -- see violations above.")
    print("=" * 70)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
