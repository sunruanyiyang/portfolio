"""
delay_encoder.py - DELAY PROPAGATION OVER SPARSE REACHABLE LEVELS

Encodes arrival-time propagation and critical-path delay constraints into
CNF using a threshold (order) encoding, exactly as before, but restricted to
a SPARSE set of "reachable" delay levels rather than every integer level in
[0, max_level].

WHY THE DENSE VERSION WAS UNUSABLE
===================================
The previous version allocated an AT[n][t] variable and encoded propagation
clauses for EVERY integer t in range(max_level + 1). With DELAY_SCALE = 100
and delay bounds expressed in picoseconds, max_level routinely reaches into
the tens of thousands (e.g. 25000 for a 250 ps bound). The propagation loop
is O(gates * gate_types * max_level * arity * gate_index), so at 24 gates
and max_level ~25000 this blows up to billions of clause-literals for a
SINGLE delay-bound test -- and search.py reruns that encoding on every step
of its binary search. This is what caused the observed hang.

WHY SPARSE LEVELS ARE SOUND
============================
A real circuit's arrival time at any node is, by construction, always
EXACTLY a sum of gate delays along some path from a primary input (arrival
0) through some sequence of at most `num_gates` gates. It can never take an
arbitrary intermediate integer value. So the true set of values Arrival(n)
can ever take, for ANY node n in ANY valid circuit with at most `num_gates`
gates, is a small, sparse set: all sums of at most `num_gates` values drawn
(with repetition) from the library's small set of distinct gate delays,
capped at the max level under test.

We compute this set once (`compute_reachable_levels`) and allocate AT
variables and propagation clauses only at those levels. This is a sound
over-approximation (it never excludes a level a real circuit could reach)
and is typically two to three orders of magnitude smaller than the dense
range, because the number of hops that fit under a given picosecond budget
is bounded by max_level / min_gate_delay, not by num_gates.

OUTPUT CONSTRAINT AT AN ARBITRARY TEST LEVEL
==============================================
Binary search in search.py tests arbitrary integer `mid_level` values that
generally will NOT themselves be reachable levels. Since arrival times only
ever land exactly on reachable levels, "Arrival(n) <= mid_level" is
equivalent to "Arrival(n) <= L" where L is the LARGEST reachable level that
is <= mid_level (nothing changes strictly between two consecutive reachable
levels). So the output constraint just reuses the AT variable at that floor
level -- no new variable or clause range is needed.

WHY NOT fanin_decoder_vars / output_decoder_vars
==================================================
Unchanged from the previous version: those decoder variables are only
forward-constrained (decoder[n] => binary==n) by structure_encoder.py and
are therefore vacuously satisfiable if left false. All delay-propagation and
output-constraint logic here is conditioned directly on the binary fanin
bits via equality/inequality literal sets, exactly as before.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

from variables import DelayVariables, StructureVariables, VariablePool
from gate_library import GATE_LIBRARY, GATE_TYPES_ORDERED, delay_level_of


def _binary_neq_literals(bit_vars: list[int], value: int) -> list[int]:
    """
    Return literals such that, when OR'd into a clause, the clause is
    automatically satisfied whenever the binary-encoded value != `value`.
    """
    literals = []
    for i, bit_var in enumerate(bit_vars):
        bit_i = (value >> i) & 1
        if bit_i == 1:
            literals.append(-bit_var)
        else:
            literals.append(bit_var)
    return literals


def compute_reachable_levels(num_gates: int, max_level: int) -> list[int]:
    """
    Compute the sparse, sorted set of delay levels that any node's arrival
    time could ever actually take, given at most `num_gates` gates and a
    cap of `max_level`.

    This is the set of all sums of 0..num_gates values drawn (with
    repetition) from the library's distinct gate-delay levels, that do not
    exceed max_level. Computed via BFS/DP layering so that it terminates
    early once no new sums fit under max_level (typically far fewer than
    num_gates layers, since chain length is also bounded by
    max_level / min_gate_delay).
    """
    deltas = sorted({delay_level_of(gt) for gt in GATE_TYPES_ORDERED})
    if not deltas:
        return [0]

    min_delta = deltas[0]

    levels = {0}
    frontier = {0}

    # Chain depth is bounded both by num_gates (structural) and by
    # max_level // min_delta (physical) -- take the smaller bound so we
    # never iterate more layers than could possibly matter.
    max_hops = num_gates
    if min_delta > 0:
        max_hops = min(max_hops, (max_level // min_delta) + 1)

    for _ in range(max_hops):
        new_frontier = set()
        for level in frontier:
            for delta in deltas:
                next_level = level + delta
                if next_level <= max_level and next_level not in levels:
                    new_frontier.add(next_level)
        if not new_frontier:
            break
        levels |= new_frontier
        frontier = new_frontier

    return sorted(levels)


def floor_reachable_level(sorted_levels: Sequence[int], target: int) -> Optional[int]:
    """
    Return the largest value in `sorted_levels` that is <= target, or None
    if every reachable level exceeds target.
    """
    lo, hi = 0, len(sorted_levels) - 1
    result = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if sorted_levels[mid] <= target:
            result = sorted_levels[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    return result


def _get_or_allocate_at_var(
    pool: VariablePool, at_vars: dict[int, dict[int, int]], node: int, level: int
) -> int:
    """Lazily allocate arrival time threshold variable."""
    if level not in at_vars[node]:
        var_id = pool.fresh_var(f"AT[node_{node}][level_{level}]")
        at_vars[node][level] = var_id
    return at_vars[node][level]


def encode_primary_input_arrival_times(
    pool: VariablePool, clause_sink: Callable[[list[int]], None], delay_vars: DelayVariables
) -> int:
    """Primary inputs have zero arrival time: AT[input][0] = true."""
    num_inputs = delay_vars.num_inputs
    clause_count = 0

    for i in range(num_inputs):
        at_var = _get_or_allocate_at_var(pool, delay_vars.at_vars, i, 0)
        clause_sink([at_var])
        clause_count += 1

    return clause_count


def encode_monotonicity_constraints(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    delay_vars: DelayVariables,
    sorted_levels: Sequence[int],
) -> int:
    """
    Enforce AT[n][t] => AT[n][t'] for consecutive reachable levels t < t'.
    Only consecutive pairs in the sparse reachable-level list need this
    clause; transitivity across the whole chain follows automatically.
    """
    clause_count = 0
    num_nodes = delay_vars.num_nodes()

    for n in range(num_nodes):
        for i in range(len(sorted_levels) - 1):
            t = sorted_levels[i]
            t_next = sorted_levels[i + 1]
            at_t = _get_or_allocate_at_var(pool, delay_vars.at_vars, n, t)
            at_t_next = _get_or_allocate_at_var(pool, delay_vars.at_vars, n, t_next)
            clause_sink([-at_t, at_t_next])
            clause_count += 1

    return clause_count


def encode_gate_delay_propagation(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables,
    delay_vars: DelayVariables,
    sorted_levels: Sequence[int],
) -> int:
    """
    Encode delay propagation directly on binary fanin bits (no decoder
    variables), restricted to the sparse set of reachable levels.

    For gate g, gate type gt (delay D), fanin position p, candidate source n,
    and reachable level t:

        Direction A: (gt selected) AND (fanin[p]==n) AND AT[g][t] => AT[n][t-D]
        Direction B: (gt selected) AND (ready on ALL positions at t-D) => AT[g][t]

    KEY FIX: ready_var[g][p][pred] is independent of gate type.
    "Is position p of gate g ready by predecessor level pred?" depends only
    on the fanin binding (binary bits) and the AT variables -- not on which
    gate type is selected. The prior version allocated a fresh ready_var
    inside the `for gt` loop, creating 7x as many variables as needed.

    Now: ready_vars are cached per (position, predecessor_level) and shared
    across all gate types. Their biconditional clauses are emitted exactly
    once per unique (gate, position, predecessor_level) triple.
    """
    num_inputs = struct_vars.num_inputs
    num_gates = struct_vars.num_gates
    clause_count = 0

    levels_set = set(sorted_levels)

    for gate_index in range(num_gates):
        g = num_inputs + gate_index

        # Cache: (position, predecessor_level) -> ready_var_id
        # Populated lazily; biconditional clauses emitted on first access.
        ready_cache: dict[tuple[int, int], int] = {}

        def _get_ready_var(p: int, pred: int) -> tuple[int, int]:
            """Return (ready_var_id, new_clauses_emitted)."""
            nonlocal clause_count
            key = (p, pred)
            if key in ready_cache:
                return ready_cache[key], 0
            rv = pool.fresh_var(f"fanin_ready[g{gate_index}][p{p}][pred{pred}]")
            ready_cache[key] = rv
            bit_vars = struct_vars.fanin_binary_vars[g][p]
            for source_node in range(g):
                neq_literals = _binary_neq_literals(bit_vars, source_node)
                source_at = _get_or_allocate_at_var(
                    pool, delay_vars.at_vars, source_node, pred
                )
                clause_sink(neq_literals + [-rv, source_at])
                clause_count += 1
                clause_sink(neq_literals + [-source_at, rv])
                clause_count += 1
            return rv, 0

        for gt in GATE_TYPES_ORDERED:
            gate_type_var = struct_vars.gate_type_vars[g][int(gt)]
            gate_spec = GATE_LIBRARY[gt]
            gate_arity = gate_spec.arity
            gate_delay_level = delay_level_of(gt)

            for t in sorted_levels:
                at_g_t = _get_or_allocate_at_var(pool, delay_vars.at_vars, g, t)

                if t < gate_delay_level:
                    clause_sink([-gate_type_var, -at_g_t])
                    clause_count += 1
                    continue

                predecessor_level = t - gate_delay_level
                if predecessor_level not in levels_set:
                    # No EXACT direct recurrence can be encoded for this t
                    # under this gate type (t - D isn't itself a reachable
                    # sum). This does NOT mean AT[g][t] must be false: the
                    # gate's true arrival may sit at an earlier reachable
                    # level, and monotonicity alone propagates that truth
                    # forward to every later level, including this t.
                    # Forcing -AT[g][t] here directly contradicts
                    # monotonicity whenever the gate's real arrival lands
                    # below t -- this was the actual bug: it made every
                    # gate type universally UNSAT as soon as any later
                    # reachable level's predecessor wasn't itself an exact
                    # reachable sum (which happens almost immediately).
                    # Correct fix: just skip direct-recurrence encoding for
                    # this (gt, t); do not emit any forcing clause.
                    continue

                # Direction A: (gt selected) AND (fanin[p]==n) AND AT[g][t]
                #              => AT[n][pred]
                for p in range(gate_arity):
                    bit_vars = struct_vars.fanin_binary_vars[g][p]
                    for source_node in range(g):
                        neq_literals = _binary_neq_literals(bit_vars, source_node)
                        source_at = _get_or_allocate_at_var(
                            pool, delay_vars.at_vars, source_node, predecessor_level
                        )
                        clause_sink([-gate_type_var, -at_g_t] + neq_literals + [source_at])
                        clause_count += 1

                # Direction B: (gt selected) AND (all positions ready at pred)
                #              => AT[g][t].
                # ready_vars are fetched (and their clauses emitted) at most
                # once per (position, predecessor_level) across all gate types.
                clause = [-gate_type_var]
                for p in range(gate_arity):
                    rv, _ = _get_ready_var(p, predecessor_level)
                    clause.append(-rv)
                clause.append(at_g_t)
                clause_sink(clause)
                clause_count += 1

    return clause_count


def encode_output_delay_constraint(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables,
    delay_vars: DelayVariables,
    max_delay_level: int,
    sorted_levels: Sequence[int],
) -> int:
    """
    Enforce AT[output][max_delay_level] = true, conditioned directly on
    output_binary_vars equality. Since arrival times only ever land exactly
    on reachable levels, this reuses the AT variable at the largest
    reachable level <= max_delay_level (see module docstring).
    """
    num_nodes = struct_vars.num_nodes()
    clause_count = 0

    floor_level = floor_reachable_level(sorted_levels, max_delay_level)
    if floor_level is None:
        # max_delay_level is below even the minimum possible arrival time
        # (0); no node can ever satisfy this. Emit an always-false clause
        # per candidate node so the whole formula becomes UNSAT, matching
        # the semantics of the original dense encoding.
        output_bit_vars = [struct_vars.output_binary_vars[i] for i in range(struct_vars.num_output_bits)]
        for n in range(num_nodes):
            neq_literals = _binary_neq_literals(output_bit_vars, n)
            clause_sink(neq_literals)
            clause_count += 1
        return clause_count

    output_bit_vars = [struct_vars.output_binary_vars[i] for i in range(struct_vars.num_output_bits)]

    for n in range(num_nodes):
        neq_literals = _binary_neq_literals(output_bit_vars, n)
        at_var = _get_or_allocate_at_var(pool, delay_vars.at_vars, n, floor_level)
        clause_sink(neq_literals + [at_var])
        clause_count += 1

    return clause_count


def encode_delay_constraints(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables,
    delay_vars: DelayVariables,
    max_delay_level: int,
    sorted_levels: Sequence[int] | None = None,
) -> int:
    """
    Top-level encoder for delay constraints, using the sparse reachable-level
    encoding. `sorted_levels` should be precomputed once per gate budget via
    `compute_reachable_levels(num_gates, upper_bound_level)` and reused
    across every binary-search test at that budget (it does not depend on
    max_delay_level, only on num_gates and the global upper bound). If not
    supplied, it is computed on the fly from max_delay_level as a fallback.
    """
    if sorted_levels is None:
        sorted_levels = compute_reachable_levels(struct_vars.num_gates, max_delay_level)

    clause_count = 0

    clause_count += encode_primary_input_arrival_times(pool, clause_sink, delay_vars)
    clause_count += encode_monotonicity_constraints(pool, clause_sink, delay_vars, sorted_levels)
    clause_count += encode_gate_delay_propagation(pool, clause_sink, struct_vars, delay_vars, sorted_levels)
    clause_count += encode_output_delay_constraint(
        pool, clause_sink, struct_vars, delay_vars, max_delay_level, sorted_levels
    )

    return clause_count
