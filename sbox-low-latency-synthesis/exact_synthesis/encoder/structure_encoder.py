"""
structure_encoder.py - HYBRID BINARY + CARDINALITY ENCODING WITH DECODER LAYER

Gate types + unused: sequential counter + commander (one-hot semantics).
Fanin selection: binary encoding with decoder layer.
Output selection: binary encoding with decoder layer.

CRITICAL FIX: Decoder consistency uses only forward direction (decoder => binary).
Decoders are NOT one-hot constrained. They are auxiliary variables constrained
only by binary bits, not by each other.
"""

from __future__ import annotations

from typing import Callable

from variables import StructureVariables, VariablePool
from gate_library import GATE_LIBRARY, GATE_TYPES_ORDERED, arity_of


def _encode_sequential_counter_onehot(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    var_ids: list[int]
) -> int:
    """
    Exactly-one constraint via Sinz's sequential AtMostOne encoding, plus an
    explicit AtLeastOne clause. O(n) clauses, O(n) auxiliary variables.

    Auxiliary variables s_0..s_{n-2}, where s_i means "at least one of
    var_ids[0..i] is true" (prefix-OR flag).
    """
    if not var_ids:
        return 0

    n = len(var_ids)
    clause_count = 0

    if n == 1:
        clause_sink([var_ids[0]])
        return 1

    # AtLeastOne
    clause_sink(list(var_ids))
    clause_count += 1

    if n == 2:
        clause_sink([-var_ids[0], -var_ids[1]])
        clause_count += 1
        return clause_count

    s = [pool.fresh_var(f"amo_s_{i}") for i in range(n - 1)]

    clause_sink([-var_ids[0], s[0]])
    clause_count += 1

    for i in range(1, n - 1):
        clause_sink([-var_ids[i], s[i]])
        clause_count += 1
        clause_sink([-s[i - 1], s[i]])
        clause_count += 1
        clause_sink([-var_ids[i], -s[i - 1]])
        clause_count += 1

    clause_sink([-var_ids[n - 1], -s[n - 2]])
    clause_count += 1

    return clause_count


def _encode_at_most_one_sequential(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    var_ids: list[int],
) -> int:
    """
    Pure AtMostOne constraint (Sinz sequential encoding), with NO AtLeastOne
    clause. Used for commander groups, where "at least one in this group" is
    only required conditionally (via the group's commander variable), not
    unconditionally.
    """
    n = len(var_ids)
    clause_count = 0

    if n <= 1:
        return 0

    if n == 2:
        clause_sink([-var_ids[0], -var_ids[1]])
        return 1

    s = [pool.fresh_var(f"amo_s_{i}") for i in range(n - 1)]

    clause_sink([-var_ids[0], s[0]])
    clause_count += 1

    for i in range(1, n - 1):
        clause_sink([-var_ids[i], s[i]])
        clause_count += 1
        clause_sink([-s[i - 1], s[i]])
        clause_count += 1
        clause_sink([-var_ids[i], -s[i - 1]])
        clause_count += 1

    clause_sink([-var_ids[n - 1], -s[n - 2]])
    clause_count += 1

    return clause_count


def _encode_commander_onehot(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    var_ids: list[int],
    threshold: int = 6,
) -> int:
    """
    Commander encoding (Klieber & Kwon) for large exactly-one sets.

    Each group gets:
      - AtMostOne within the group (unconditional; correct, since at most one
        variable in a group can ever be true regardless of which group is
        "active").
      - v => commander, for every v in the group (if any group member is
        true, its commander must be true).
      - commander => OR(group members) (if the commander is true, at least
        one group member must be true) -- this is what CONDITIONS the
        group's "at least one" on that group actually being selected,
        instead of forcing it unconditionally.

    Finally, exactly-one is enforced over the commander variables themselves,
    which (combined with the per-group linkage above) yields exactly-one
    over the full original variable set.
    """
    if len(var_ids) <= threshold:
        return _encode_sequential_counter_onehot(pool, clause_sink, var_ids)

    clause_count = 0
    group_size = threshold
    num_groups = (len(var_ids) + group_size - 1) // group_size

    group_commanders = []

    for g in range(num_groups):
        start_idx = g * group_size
        end_idx = min((g + 1) * group_size, len(var_ids))
        group_vars = var_ids[start_idx:end_idx]

        commander = pool.fresh_var(f"cmd_{g}")
        group_commanders.append(commander)

        # AtMostOne WITHIN the group (unconditional; correct).
        clause_count += _encode_at_most_one_sequential(pool, clause_sink, group_vars)

        # v => commander, for every group member.
        for var in group_vars:
            clause_sink([-var, commander])
            clause_count += 1

        # commander => OR(group members). This is what makes "at least one
        # in this group" CONDITIONAL on the group being selected, rather than
        # an unconditional requirement.
        clause_sink([-commander] + list(group_vars))
        clause_count += 1

    # Exactly-one over the commanders themselves.
    clause_count += _encode_sequential_counter_onehot(pool, clause_sink, group_commanders)

    return clause_count


def _encode_binary_less_than(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    bit_vars: list[int],
    max_val: int,
) -> int:
    """Constrain binary-encoded value < max_val. O(max_val) clauses."""
    if not bit_vars or max_val >= (1 << len(bit_vars)):
        return 0

    clause_count = 0
    num_bits = len(bit_vars)

    for candidate in range(max_val, 1 << num_bits):
        clause = []
        for i in range(num_bits):
            bit_i = (candidate >> i) & 1
            if bit_i == 1:
                clause.append(-bit_vars[i])
            else:
                clause.append(bit_vars[i])
        clause_sink(clause)
        clause_count += 1

    return clause_count


def encode_gate_type_onehot(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables
) -> int:
    """Gate type + unused as exactly-one via commander encoding."""
    num_inputs = struct_vars.num_inputs
    num_gates = struct_vars.num_gates
    clause_count = 0

    for g in range(num_inputs, num_inputs + num_gates):
        gate_types = [struct_vars.gate_type_vars[g][int(gt)] for gt in GATE_TYPES_ORDERED]
        unused = struct_vars.unused_vars[g]

        all_options = gate_types + [unused]

        clause_count += _encode_commander_onehot(pool, clause_sink, all_options, threshold=6)

    return clause_count


def encode_fanin_selection_binary(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables
) -> int:
    """Fanin selection via binary encoding with topological range constraint."""
    num_inputs = struct_vars.num_inputs
    num_gates = struct_vars.num_gates
    clause_count = 0

    for g in range(num_inputs, num_inputs + num_gates):
        for p in range(len(struct_vars.fanin_binary_vars[g])):
            bit_vars = struct_vars.fanin_binary_vars[g][p]

            clause_count += _encode_binary_less_than(pool, clause_sink, bit_vars, g)

    return clause_count


def encode_output_selection_binary(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables
) -> int:
    """Output selection via binary encoding with range constraint."""
    num_nodes = struct_vars.num_nodes()
    bit_vars = [struct_vars.output_binary_vars[i] for i in range(struct_vars.num_output_bits)]

    return _encode_binary_less_than(pool, clause_sink, bit_vars, num_nodes)


def encode_output_not_unused(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables
) -> int:
    """
    Forbid selecting an unused gate as the circuit output.

    Without this constraint, an unused gate has no function constraints
    applied to its signal variable (every gate-type clause is disabled by
    -gate_type_var when all gate types are false), leaving its signal
    completely free. If such a gate is then selected as output, the solver
    can set that free signal directly to the target truth table, producing
    a semantically meaningless "0 delay, 0 gate" solution.

    For every gate node g: (output_binary != g) OR (NOT unused[g]).
    """
    num_inputs = struct_vars.num_inputs
    num_gates = struct_vars.num_gates
    clause_count = 0

    bit_vars = [struct_vars.output_binary_vars[i] for i in range(struct_vars.num_output_bits)]

    for gate_index in range(num_gates):
        g = num_inputs + gate_index
        unused_var = struct_vars.unused_vars[g]

        neq_literals = []
        for i, bit_var in enumerate(bit_vars):
            bit_i = (g >> i) & 1
            if bit_i == 1:
                neq_literals.append(-bit_var)
            else:
                neq_literals.append(bit_var)

        clause_sink(neq_literals + [-unused_var])
        clause_count += 1

    return clause_count


def encode_decoder_consistency(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables
) -> int:
    """
    Enforce forward direction only: decoder[n] => (binary == n)
    
    CRITICAL: Do NOT enforce (binary == n) => decoder[n]
    
    The decoders are auxiliary variables used by function/delay encoders.
    They are NOT one-hot constrained amongst themselves.
    
    Each decoder[n] is true iff the binary bits encode value n.
    Multiple decoders can be true simultaneously if their corresponding
    binary encodings are satisfied (though only one should be by design).
    """
    num_inputs = struct_vars.num_inputs
    num_gates = struct_vars.num_gates
    clause_count = 0

    # Fanin decoder consistency - forward direction only
    for g in range(num_inputs, num_inputs + num_gates):
        for p in range(len(struct_vars.fanin_binary_vars[g])):
            bit_vars = struct_vars.fanin_binary_vars[g][p]
            decoder_vars = struct_vars.fanin_decoder_vars[g][p]

            for n in range(g):
                decoder_var = decoder_vars[n]

                # FORWARD ONLY: decoder[n] => (binary_bits == n)
                # -decoder[n] | (bits match n for all positions)
                direction_a_clause = [-decoder_var]
                for i in range(len(bit_vars)):
                    bit_i = (n >> i) & 1
                    if bit_i == 1:
                        direction_a_clause.append(bit_vars[i])
                    else:
                        direction_a_clause.append(-bit_vars[i])
                clause_sink(direction_a_clause)
                clause_count += 1

    # Output decoder consistency - forward direction only
    bit_vars = [struct_vars.output_binary_vars[i] for i in range(struct_vars.num_output_bits)]
    decoder_vars = struct_vars.output_decoder_vars

    for n in range(struct_vars.num_nodes()):
        decoder_var = decoder_vars[n]

        # FORWARD ONLY: decoder[n] => (binary_bits == n)
        direction_a_clause = [-decoder_var]
        for i in range(len(bit_vars)):
            bit_i = (n >> i) & 1
            if bit_i == 1:
                direction_a_clause.append(bit_vars[i])
            else:
                direction_a_clause.append(-bit_vars[i])
        clause_sink(direction_a_clause)
        clause_count += 1

    return clause_count


def encode_gate_type_arity_consistency(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables
) -> int:
    """
    Arity consistency: higher fanin positions are ignored by decoder.
    No CNF clauses needed (handled in decoder logic).
    """
    return 0


def encode_unused_gate_chain(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables
) -> int:
    """Symmetry breaking: if gate g is unused, all later gates must be unused."""
    num_inputs = struct_vars.num_inputs
    num_gates = struct_vars.num_gates
    clause_count = 0

    for g in range(num_inputs, num_inputs + num_gates - 1):
        for g_prime in range(g + 1, num_inputs + num_gates):
            unused_g = struct_vars.unused_vars[g]
            unused_g_prime = struct_vars.unused_vars[g_prime]
            clause_sink([-unused_g, unused_g_prime])
            clause_count += 1

    return clause_count


def encode_structure_constraints(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables
) -> int:
    """Top-level structure encoder with hybrid binary + cardinality + decoder layer."""
    clause_count = 0

    clause_count += encode_gate_type_onehot(pool, clause_sink, struct_vars)
    clause_count += encode_fanin_selection_binary(pool, clause_sink, struct_vars)
    clause_count += encode_output_selection_binary(pool, clause_sink, struct_vars)
    clause_count += encode_output_not_unused(pool, clause_sink, struct_vars)
    clause_count += encode_gate_type_arity_consistency(pool, clause_sink, struct_vars)
    clause_count += encode_unused_gate_chain(pool, clause_sink, struct_vars)
    clause_count += encode_decoder_consistency(pool, clause_sink, struct_vars)

    return clause_count


def _binary_decode(bit_vars: list[int], model: dict[int, bool]) -> int:
    """Decode binary value from model."""
    value = 0
    for i, bit_var in enumerate(bit_vars):
        if model.get(bit_var, False):
            value |= (1 << i)
    return value


def get_selected_gate_type(
    struct_vars: StructureVariables,
    model: dict[int, bool],
    gate_index: int
) -> int | None:
    """Extract selected gate type from model."""
    num_inputs = struct_vars.num_inputs
    g = num_inputs + gate_index

    unused_var = struct_vars.unused_vars[g]
    if model.get(unused_var, False):
        return None

    selected_types = []
    for gt in GATE_TYPES_ORDERED:
        type_var = struct_vars.gate_type_vars[g][int(gt)]
        if model.get(type_var, False):
            selected_types.append(int(gt))

    if len(selected_types) != 1:
        raise RuntimeError(f"Gate {gate_index} has {len(selected_types)} selected types, expected 1.")

    return selected_types[0]


def get_selected_fanins(
    struct_vars: StructureVariables,
    model: dict[int, bool],
    gate_index: int
) -> list[int]:
    """Extract selected fanins from model."""
    num_inputs = struct_vars.num_inputs
    g = num_inputs + gate_index

    selected_gate_type = get_selected_gate_type(struct_vars, model, gate_index)
    if selected_gate_type is None:
        return []

    gate_spec = GATE_LIBRARY[selected_gate_type]
    gate_arity = gate_spec.arity

    fanins = []
    for p in range(min(gate_arity, len(struct_vars.fanin_binary_vars[g]))):
        bit_vars = struct_vars.fanin_binary_vars[g][p]
        fanin_node = _binary_decode(bit_vars, model)
        fanins.append(fanin_node)

    return fanins


def get_selected_output(
    struct_vars: StructureVariables,
    model: dict[int, bool]
) -> int:
    """Extract selected output node from model."""
    bit_vars = [struct_vars.output_binary_vars[i] for i in range(struct_vars.num_output_bits)]
    return _binary_decode(bit_vars, model)