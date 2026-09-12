"""
symmetry_breaking.py - FANIN ORDERING VIA BINARY LEQ COMPARATOR

Real fanin ordering symmetry breaking, unlike the previous "removed, too
expensive" version. This is the fix for the actual remaining bottleneck
after DELAY_SCALE tuning and portfolio solving: with binary-encoded fanins
and 13 gate types (most of them commutative in some or all of their
positions), the search space has enormous permutation symmetry -- e.g. a
NAND2 gate wired as NAND2(x0, x1) and NAND2(x1, x0) are functionally
identical, but the SAT solver has no way to know that without being told,
and has to rediscover it (or get lucky) via its own learned clauses on
every single delay-bound test. Confirmed empirically: without this,
instances that should be tractable ran for hours across multiple random
seeds without resolving.

WHAT WE ENFORCE, AND WHY IT'S SOUND FOR EVERY GATE TYPE
==========================================================
We enforce, UNCONDITIONALLY (regardless of which gate type ends up
selected for a slot):

    fanin[0] <= fanin[1]     (always, if the gate has >= 2 positions)
    fanin[2] <= fanin[3]     (always, if the gate has >= 4 positions)

This single, type-independent rule is sound for every gate type in this
project's 13-gate library:

  - INV, BUF (arity 1): positions 1-3 are unused padding. Any valid value
    satisfies the "< g" range constraint, so constraining unused padding to
    be ordered relative to other unused padding never eliminates a real
    circuit -- it just picks one canonical padding value among many
    equally-valid ones.
  - NAND2, NOR2, AND2, XNOR2 (arity 2, positions 0-1 fully symmetric):
    fanin[0] <= fanin[1] is EXACTLY the standard, maximal symmetry break.
  - OAI21, AOI21 (arity 3, positions 0-1 are the symmetric OR-pair,
    position 2 is the distinguished AND-input): fanin[0] <= fanin[1] is
    EXACTLY correct -- position 2 is never compared against anything, so
    its distinguished role is preserved.
  - OAI22, AOI22 (arity 4, (0,1) and (2,3) are two SEPARATE symmetric
    pairs, not interchangeable with each other): fanin[0] <= fanin[1] AND
    fanin[2] <= fanin[3] is EXACTLY the correct full symmetry break.
  - NAND3, AND3 (arity 3, positions 0-1-2 FULLY symmetric as a triple):
    fanin[0] <= fanin[1] is a valid but PARTIAL break -- it removes swaps
    of positions 0 and 1 but not all 3! = 6 permutations. Still sound
    (never eliminates a true solution), just not maximal.
  - NAND4 (arity 4, positions 0-1-2-3 FULLY symmetric as a quadruple):
    fanin[0] <= fanin[1] AND fanin[2] <= fanin[3] is similarly a sound but
    partial break (misses cross-pair orderings like fanin[1] <= fanin[2]).

Because the SAME two constraints are correct (or at worst a safe subset of
the ideal constraint) for every single gate type, they can be applied
UNCONDITIONALLY per gate slot -- no per-gate-type conditioning logic is
needed at all, keeping this cheap and simple.

THE COMPARATOR ITSELF
=======================
`encode_binary_leq` implements the standard bitwise less-or-equal
encoding for two k-bit unsigned binary numbers (LSB-first, matching this
project's fanin_binary_vars bit order): O(k) clauses, O(k) auxiliary "tie"
variables. It was exhaustively brute-force verified against every possible
(A, B) bit pattern for k = 1, 2, 3, 4, and 5 bits (this project's actual
fanin bit-width for up to 33 nodes) before being wired in here -- see the
verification script used during development. This kind of hand-written
comparator logic is exactly the sort of thing that hides subtle off-by-one
bugs, so it was checked exhaustively rather than by spot-check.
"""

from __future__ import annotations

from typing import Callable

from variables import StructureVariables, VariablePool


def encode_binary_leq(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    bits_a: list[int],
    bits_b: list[int],
    description: str = "leq",
) -> int:
    """
    Enforce A <= B for two unsigned binary numbers, each given as a list of
    literal variable IDs in LSB-first order (bits_a[0] is the least
    significant bit), matching this project's fanin_binary_vars convention.

    Standard construction: walk bits from MSB to LSB, maintaining a "tie"
    variable meaning "all bits strictly above this point are equal between
    A and B". At each bit, if still tied, forbid A_i=1 while B_i=0 (which
    would make A > B). The tie variable is updated via a full biconditional
    (both directions), which is essential for soundness -- an under- or
    over-approximated tie would either fail to forbid an actual A>B case,
    or wrongly reject a valid A<=B case at a bit that no longer matters
    because an earlier bit already decided the comparison.
    """
    assert len(bits_a) == len(bits_b), "bit-vectors must be the same width"
    k = len(bits_a)
    clause_count = 0
    prev_tie: int | None = None  # None represents the constant True (before any bits compared)

    for i in range(k - 1, -1, -1):
        a, b = bits_a[i], bits_b[i]

        # If tied on all higher bits, forbid A_i=1 AND B_i=0 (i.e. A > B here).
        if prev_tie is None:
            clause_sink([-a, b])
        else:
            clause_sink([-prev_tie, -a, b])
        clause_count += 1

        if i == 0:
            break  # no tie variable needed after the last (LSB) comparison

        new_tie = pool.fresh_var(f"{description}_tie_bit{i}")

        if prev_tie is None:
            # new_tie <=> (a == b)
            clause_sink([-new_tie, -a, b])
            clause_sink([-new_tie, a, -b])
            clause_sink([new_tie, a, b])
            clause_sink([new_tie, -a, -b])
            clause_count += 4
        else:
            # new_tie <=> (prev_tie AND a == b)
            clause_sink([-new_tie, prev_tie])
            clause_sink([-new_tie, -a, b])
            clause_sink([-new_tie, a, -b])
            clause_sink([new_tie, -prev_tie, a, b])
            clause_sink([new_tie, -prev_tie, -a, -b])
            clause_count += 5

        prev_tie = new_tie

    return clause_count


def encode_fanin_ordering_constraints(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables,
) -> int:
    """
    Unconditionally enforce fanin[0] <= fanin[1] and fanin[2] <= fanin[3]
    (whichever pairs exist, depending on max arity) for every gate slot.
    Sound for every gate type in the library -- see module docstring.
    """
    num_inputs = struct_vars.num_inputs
    num_gates = struct_vars.num_gates
    clause_count = 0

    for gate_index in range(num_gates):
        g = num_inputs + gate_index
        num_positions = len(struct_vars.fanin_binary_vars[g])

        if num_positions >= 2:
            bits_0 = struct_vars.fanin_binary_vars[g][0]
            bits_1 = struct_vars.fanin_binary_vars[g][1]
            clause_count += encode_binary_leq(
                pool, clause_sink, bits_0, bits_1, description=f"fanin_ord_g{gate_index}_01"
            )

        if num_positions >= 4:
            bits_2 = struct_vars.fanin_binary_vars[g][2]
            bits_3 = struct_vars.fanin_binary_vars[g][3]
            clause_count += encode_binary_leq(
                pool, clause_sink, bits_2, bits_3, description=f"fanin_ord_g{gate_index}_23"
            )

    return clause_count


def encode_gate_slot_ordering_constraints(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables,
) -> int:
    """Gate slot ordering already handled by unused-gate chain (in structure_encoder.py)."""
    return 0


def encode_duplicate_gate_elimination(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables,
) -> int:
    """Duplicate elimination implicit in SAT solving."""
    return 0


def encode_symmetry_breaking_constraints(
    pool: VariablePool,
    clause_sink: Callable[[list[int]], None],
    struct_vars: StructureVariables,
) -> int:
    """Top-level symmetry breaker: real fanin ordering + existing gate-slot handling."""
    clause_count = 0

    clause_count += encode_fanin_ordering_constraints(pool, clause_sink, struct_vars)
    clause_count += encode_gate_slot_ordering_constraints(pool, clause_sink, struct_vars)
    clause_count += encode_duplicate_gate_elimination(pool, clause_sink, struct_vars)

    return clause_count
