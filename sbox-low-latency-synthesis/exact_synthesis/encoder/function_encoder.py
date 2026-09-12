"""
function_encoder.py - TEXTBOOK SAT-BASED EXACT LOGIC SYNTHESIS

Encodes Boolean function constraints following the standard architecture
from recent literature (Soeken, Haaswijk, Mishchenko, et al.).

Three-phase approach per (gate, minterm):
1. Fanin multiplexing: mux[g][p][m] <-> signal[source_node][m]
2. Gate function: signal[g][m] <-> truth_table(mux[g][0][m], ...)
3. Output mapping: selected_output_signal <-> target_truth_table_value

Each phase is fully Tseitin-encoded (biconditional, not just implications).
Fanin enumeration is linear O(g) per position, gate function is O(2^arity)
independent of g. Total: O(gates * num_minterms * (arity * gates + 2^arity)).
"""

from __future__ import annotations

from typing import Callable

from variables import StructureVariables, VariablePool
from gate_library import GATE_LIBRARY, GATE_TYPES_ORDERED
from truth_table import all_minterms, target_output_bit


def _binary_neq_literals(bit_vars: list[int], value: int) -> list[int]:
    """
    Literals that are true iff binary-encoded value != target value.
    Used to express "(fanin_binary[g][p] != source_node)" compactly.
    """
    literals = []
    for i, bit_var in enumerate(bit_vars):
        bit_i = (value >> i) & 1
        if bit_i == 1:
            literals.append(-bit_var)
        else:
            literals.append(bit_var)
    return literals


def encode_primary_input_signals(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables,
) -> int:
    """Fix signal[input][m] for all minterms m."""
    num_inputs = struct_vars.num_inputs
    clause_count = 0

    for i in range(num_inputs):
        for m in all_minterms(num_inputs):
            bit_value = (m >> i) & 1
            signal_var = struct_vars.signal_vars[i][m]
            clause_sink([signal_var] if bit_value else [-signal_var])
            clause_count += 1

    return clause_count


def encode_fanin_mux_for_minterm(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables,
    minterm: int,
    mux_vars: dict[tuple[int, int], int],
) -> int:
    """
    Step B: Encode fanin multiplexing for all gates at a single minterm.

    For each gate g and fanin position p:
        mux[g][p][m] <-> signal[ fanin_binary_vars[g][p] ][m]

    Biconditional encoding (forward + backward):
        For each candidate source node n in [0, g):
            (fanin_binary[g][p] != n) | (-mux[g][p][m] | signal[n][m])  [forward]
            (fanin_binary[g][p] != n) | (-signal[n][m] | mux[g][p][m])  [backward]
    """
    num_inputs = struct_vars.num_inputs
    num_gates = struct_vars.num_gates
    clause_count = 0

    for gate_index in range(num_gates):
        g = num_inputs + gate_index
        for p in range(len(struct_vars.fanin_binary_vars[g])):
            mux_var = mux_vars[(g, p)]
            bit_vars = struct_vars.fanin_binary_vars[g][p]

            for source_node in range(g):
                neq_literals = _binary_neq_literals(bit_vars, source_node)
                signal_source = struct_vars.signal_vars[source_node][minterm]

                # Biconditional: (binary == source) => (mux <=> signal[source])
                #
                # Forward:  (binary==source) => (mux => signal[source])
                # Backward: (binary==source) => (signal[source] => mux)
                #
                # The backward direction is safe here because neq_literals guard it:
                # when binary != source, the clause is vacuously true. When binary==source
                # (exactly one candidate), it forces mux=signal[source], which is correct.
                # Without the backward clause, mux can be 0 even when signal[source]=1,
                # letting the Tseitin clauses see all-zero mux inputs and assign signal[g]
                # freely, breaking signal consistency.
                clause_sink(neq_literals + [-mux_var, signal_source])    # forward
                clause_count += 1
                clause_sink(neq_literals + [-signal_source, mux_var])    # backward
                clause_count += 1

    return clause_count


def encode_gate_tseitin_for_minterm(
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables,
    minterm: int,
    mux_vars: dict[tuple[int, int], int],
) -> int:
    """
    Step C: Encode gate function (Tseitin truth table) for all gates at a single minterm.

    For each gate g and gate type gt (with arity a and truth table T):
        signal[g][m] <-> T( mux[g][0][m], ..., mux[g][a-1][m] )

    Standard Tseitin biconditional:
        For each row in 2^a truth table rows:
            Forward: (row bits match inputs) => (gate_output = T[row])
            Backward: (gate_output = T[row]) => (row bits match inputs)

    Conditioned on gate type selection via one literal per clause.
    """
    num_inputs = struct_vars.num_inputs
    num_gates = struct_vars.num_gates
    clause_count = 0

    for gate_index in range(num_gates):
        g = num_inputs + gate_index
        signal_g = struct_vars.signal_vars[g][minterm]

        for gt in GATE_TYPES_ORDERED:
            gate_type_var = struct_vars.gate_type_vars[g][int(gt)]
            gate_spec = GATE_LIBRARY[gt]
            arity = gate_spec.arity
            truth_table = gate_spec.truth_table

            mux_vars_for_arity = [mux_vars[(g, p)] for p in range(arity)]

            for row_index in range(1 << arity):
                output_bit = truth_table[row_index]

                # Forward: (gate_type selected) AND (mux bits match row) => (signal[g] = output)
                forward_clause = [-gate_type_var]
                for p in range(arity):
                    required_bit = (row_index >> p) & 1
                    if required_bit == 1:
                        forward_clause.append(-mux_vars_for_arity[p])
                    else:
                        forward_clause.append(mux_vars_for_arity[p])

                if output_bit == 1:
                    forward_clause.append(signal_g)
                else:
                    forward_clause.append(-signal_g)

                clause_sink(forward_clause)
                clause_count += 1

                # NOTE: No backward clause here. The forward clause above,
                # applied across all 2**arity rows, already fully determines
                # signal_g as a function of the mux bits (given gate_type_var):
                # since mux bits are ordinary Booleans, they match exactly one
                # row, and that row's forward clause pins signal_g to the
                # correct value. A backward clause of the form used
                # previously ("match => signal = NOT output_bit") directly
                # contradicts the forward clause for that same row and caused
                # universal UNSAT.

    return clause_count


def encode_output_constraint_for_minterm(
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables,
    minterm: int,
    target_value: int,
) -> int:
    """
    Step D: Output mapping constraint.

    For each candidate output node n:
        (output_binary != n) | (signal[n][m] = target_value)
    """
    num_nodes = struct_vars.num_nodes()
    output_bit_vars = [struct_vars.output_binary_vars[i] for i in range(struct_vars.num_output_bits)]
    clause_count = 0

    for n in range(num_nodes):
        neq_literals = _binary_neq_literals(output_bit_vars, n)
        signal_n = struct_vars.signal_vars[n][minterm]

        if target_value == 1:
            clause_sink(neq_literals + [signal_n])
        else:
            clause_sink(neq_literals + [-signal_n])

        clause_count += 1

    return clause_count


def encode_function_constraints(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables,
    target_truth_table_int: int,
) -> int:
    """
    Top-level function encoder.

    1. Fix primary inputs for all minterms (unit clauses).
    2. For each minterm:
       a. Allocate per-minterm mux[g][p][m] variables (scope-local to this minterm).
       b. Encode fanin multiplexing (Tseitin biconditional).
       c. Encode gate functions (Tseitin truth table).
       d. Encode output constraint.
    """
    num_inputs = struct_vars.num_inputs
    num_gates = struct_vars.num_gates
    
    # Determine max_arity from actual fanin_binary_vars allocation width
    max_arity = 0
    if num_gates > 0:
        for gate_index in range(num_gates):
            g = num_inputs + gate_index
            max_arity = max(max_arity, len(struct_vars.fanin_binary_vars[g]))

    clause_count = 0

    # Phase 1: Fix primary inputs
    clause_count += encode_primary_input_signals(pool, clause_sink, struct_vars)

    # Phase 2: For each minterm, encode gates and output
    for minterm in all_minterms(num_inputs):
        target_val = target_output_bit(minterm, target_truth_table_int)

        # Allocate mux variables for this minterm (scope-local)
        mux_vars: dict[tuple[int, int], int] = {}
        for gate_index in range(num_gates):
            g = num_inputs + gate_index
            num_positions = len(struct_vars.fanin_binary_vars[g])
            for p in range(num_positions):
                mux_vars[(g, p)] = pool.fresh_var(f"mux[g{gate_index}][p{p}][m{minterm}]")

        # Encode steps B, C, D for this minterm
        clause_count += encode_fanin_mux_for_minterm(pool, clause_sink, struct_vars, minterm, mux_vars)
        clause_count += encode_gate_tseitin_for_minterm(clause_sink, struct_vars, minterm, mux_vars)
        clause_count += encode_output_constraint_for_minterm(clause_sink, struct_vars, minterm, target_val)

    return clause_count