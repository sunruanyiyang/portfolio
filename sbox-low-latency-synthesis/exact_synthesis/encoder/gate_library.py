"""
gate_library.py

Formal, machine-readable description of the fixed combinational standard-cell
gate library permitted in this synthesis engine. Every other module (in
particular structure_encoder.py, function_encoder.py, and delay_encoder.py)
must obtain gate arity, gate truth-table semantics, and gate delay values
exclusively from this module -- no gate semantics or delay constants may be
hard-coded elsewhere.

Permitted gates (and only these):

    INV     : 1-input inverter                    delay = 22.048 ps
    NAND2   : 2-input NAND                         delay = 27.886 ps
    NOR2    : 2-input NOR                          delay = 40.650 ps
    AND2    : 2-input AND                          delay = 40.171 ps
    NAND3   : 3-input NAND                         delay = 34.767 ps
    OAI21   : AND-OR-Invert, 3 inputs (a, b, c) -> !((a | b) & c)
                                                    delay = 32.651 ps
    NAND4   : 4-input NAND                         delay = 44.487 ps

Each gate type's Boolean function is defined generatively via a Python
callable operating on a tuple of 0/1 integers (one per fanin, in canonical
fanin-position order), together with an explicit enumeration of that
function's full truth table (as a tuple indexed by the fanin assignment's
integer encoding), so that function_encoder.py can generate CNF clauses
purely mechanically from the truth table without any gate-specific
special-casing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Sequence

from config import ps_to_level


class GateType(IntEnum):
    """
    Enumeration of every permitted gate primitive. The integer values are
    used directly as stable indices into per-gate-type variable arrays
    throughout structure_encoder.py, function_encoder.py, and
    delay_encoder.py, so this enumeration's member order and integer values
    must never be changed once other modules depend on it (they are treated
    as a fixed, canonical ordering for one-hot gate-type variables).

    NEW GATE TYPES (BUF, AOI21, AND3, OAI22, XNOR2, AOI22) are appended AFTER
    the original 7 members, at NEW integer values (7-12). This is
    deliberate: the original members (INV=0 .. NAND4=6) keep their exact
    original integer values, so any code, serialized data, or reasoning that
    depended on those specific values remains valid. Never renumber an
    existing member; always append new ones at the end.
    """

    INV = 0
    NAND2 = 1
    NOR2 = 2
    AND2 = 3
    NAND3 = 4
    OAI21 = 5
    NAND4 = 6
    BUF = 7
    AOI21 = 8
    AND3 = 9
    OAI22 = 10
    XNOR2 = 11
    AOI22 = 12


@dataclass(frozen=True)
class GateSpec:
    """
    Complete formal specification of a single gate primitive.

    Attributes:
        gate_type:   The GateType enum member this spec describes.
        name:        Human-readable/Verilog-friendly gate name.
        arity:       Number of fanin operands the gate consumes.
        function:    A callable mapping a tuple of `arity` 0/1 ints (fanin
                     values, in canonical order) to the gate's 0/1 output.
        truth_table: A tuple of length `2**arity` where entry `i` is the
                     gate's output when its fanins take on the Boolean
                     assignment whose bits (bit 0 = first fanin) equal the
                     binary representation of `i`. This is redundant with
                     `function` but pre-materialized for fast, allocation-free
                     lookups inside the (potentially very hot) CNF-generation
                     loops in function_encoder.py.
        delay_ps:    Fixed gate delay in picoseconds, as given by the target
                     technology characterization.
        verilog_op:  Verilog primitive gate keyword(s) used when instantiating
                     this gate in the exported netlist (export_verilog.py).
                     For OAI21, which has no single built-in Verilog gate
                     primitive, this is `None` and export_verilog.py emits an
                     explicit `assign` statement instead of a primitive
                     instantiation.
    """

    gate_type: GateType
    name: str
    arity: int
    function: Callable[[Sequence[int]], int]
    truth_table: tuple[int, ...]
    delay_ps: float
    verilog_op: str | None

    @property
    def delay_level(self) -> int:
        """Gate delay expressed as an integer discretized delay level."""
        return ps_to_level(self.delay_ps)

    def evaluate(self, fanin_values: Sequence[int]) -> int:
        """
        Evaluate this gate's Boolean output given a sequence of `arity`
        0/1 fanin values, using the pre-materialized truth table for an
        O(1) lookup (bit `j` of the lookup index corresponds to fanin `j`).
        """
        if len(fanin_values) != self.arity:
            raise ValueError(
                f"Gate {self.name} expects {self.arity} fanins, "
                f"got {len(fanin_values)}."
            )
        index = 0
        for j, v in enumerate(fanin_values):
            if v not in (0, 1):
                raise ValueError(f"Fanin value must be 0 or 1, got {v!r}.")
            index |= (v & 1) << j
        return self.truth_table[index]


def _materialize_truth_table(arity: int, function: Callable[[Sequence[int]], int]) -> tuple[int, ...]:
    """
    Given a gate arity and its Boolean function (as a callable over a tuple
    of 0/1 fanin values), mechanically enumerate all `2**arity` fanin
    assignments in canonical bit order and materialize the resulting truth
    table tuple. This is the single generative mechanism used to build every
    gate's truth table -- no truth table below is written out by hand as a
    literal tuple; each is produced by this function from the gate's
    algebraic definition.
    """
    table = []
    for index in range(1 << arity):
        fanins = tuple((index >> j) & 1 for j in range(arity))
        table.append(function(fanins))
    return tuple(table)


def _inv_fn(f: Sequence[int]) -> int:
    (a,) = f
    return 1 - a


def _nand2_fn(f: Sequence[int]) -> int:
    a, b = f
    return 1 - (a & b)


def _nor2_fn(f: Sequence[int]) -> int:
    a, b = f
    return 1 - (a | b)


def _and2_fn(f: Sequence[int]) -> int:
    a, b = f
    return a & b


def _nand3_fn(f: Sequence[int]) -> int:
    a, b, c = f
    return 1 - (a & b & c)


def _oai21_fn(f: Sequence[int]) -> int:
    # OAI21: output = !((a | b) & c)
    a, b, c = f
    return 1 - ((a | b) & c)


def _nand4_fn(f: Sequence[int]) -> int:
    a, b, c, d = f
    return 1 - (a & b & c & d)


def _buf_fn(f: Sequence[int]) -> int:
    (a,) = f
    return a


def _aoi21_fn(f: Sequence[int]) -> int:
    # AOI21: output = !((A1 & A2) | B1)
    a, b, c = f
    return 1 - ((a & b) | c)


def _and3_fn(f: Sequence[int]) -> int:
    a, b, c = f
    return a & b & c


def _oai22_fn(f: Sequence[int]) -> int:
    # OAI22: output = !((A1 | A2) & (B1 | B2))
    a, b, c, d = f
    return 1 - ((a | b) & (c | d))


def _xnor2_fn(f: Sequence[int]) -> int:
    a, b = f
    return 1 - (a ^ b)


def _aoi22_fn(f: Sequence[int]) -> int:
    # AOI22: output = !((A1 & A2) | (B1 & B2))
    a, b, c, d = f
    return 1 - ((a & b) | (c & d))


def _build_gate_library() -> dict[GateType, GateSpec]:
    """
    Construct the canonical, immutable mapping from GateType to its full
    GateSpec, including mechanically materialized truth tables and the
    fixed delay constants specified by the target technology
    characterization for this study.
    """
    specs: dict[GateType, GateSpec] = {}

    definitions: list[tuple[GateType, str, int, Callable[[Sequence[int]], int], float, str | None]] = [
        (GateType.INV, "INV", 1, _inv_fn, 22.048, "not"),
        (GateType.NAND2, "NAND2", 2, _nand2_fn, 27.886, "nand"),
        (GateType.NOR2, "NOR2", 2, _nor2_fn, 40.650, "nor"),
        (GateType.AND2, "AND2", 2, _and2_fn, 40.171, "and"),
        (GateType.NAND3, "NAND3", 3, _nand3_fn, 34.767, "nand"),
        (GateType.OAI21, "OAI21", 3, _oai21_fn, 32.651, None),
        (GateType.NAND4, "NAND4", 4, _nand4_fn, 44.487, "nand"),
        (GateType.BUF, "BUF", 1, _buf_fn, 33.557, "buf"),
        (GateType.AOI21, "AOI21", 3, _aoi21_fn, 51.619, None),
        (GateType.AND3, "AND3", 3, _and3_fn, 51.869, "and"),
        (GateType.OAI22, "OAI22", 4, _oai22_fn, 54.596, None),
        (GateType.XNOR2, "XNOR2", 2, _xnor2_fn, 57.604, "xnor"),
        (GateType.AOI22, "AOI22", 4, _aoi22_fn, 57.255, None),
    ]

    for gate_type, name, arity, function, delay_ps, verilog_op in definitions:
        truth_table = _materialize_truth_table(arity, function)
        specs[gate_type] = GateSpec(
            gate_type=gate_type,
            name=name,
            arity=arity,
            function=function,
            truth_table=truth_table,
            delay_ps=delay_ps,
            verilog_op=verilog_op,
        )

    return specs


#: Canonical, immutable registry mapping every GateType to its full formal
#: specification. This is the single source of truth for gate semantics and
#: delay throughout the entire project.
GATE_LIBRARY: dict[GateType, GateSpec] = _build_gate_library()

#: Gate types listed in a fixed, canonical iteration order (ascending
#: GateType integer value), used everywhere a stable enumeration order over
#: gate types is required (one-hot variable allocation, clause generation,
#: reporting).
GATE_TYPES_ORDERED: tuple[GateType, ...] = tuple(sorted(GATE_LIBRARY.keys(), key=int))

#: Maximum arity across the entire library (NAND4 => 4). Re-exported here
#: for convenience; must always agree with config.MAX_GATE_ARITY.
MAX_ARITY: int = max(spec.arity for spec in GATE_LIBRARY.values())


def gate_spec(gate_type: GateType) -> GateSpec:
    """Look up the GateSpec for a given GateType. Raises KeyError if unknown."""
    return GATE_LIBRARY[gate_type]


def arity_of(gate_type: GateType) -> int:
    """Convenience accessor: fanin arity of the given gate type."""
    return GATE_LIBRARY[gate_type].arity


def delay_level_of(gate_type: GateType) -> int:
    """Convenience accessor: discretized delay level of the given gate type."""
    return GATE_LIBRARY[gate_type].delay_level


def delay_ps_of(gate_type: GateType) -> float:
    """Convenience accessor: raw picosecond delay of the given gate type."""
    return GATE_LIBRARY[gate_type].delay_ps


def is_commutative(gate_type: GateType) -> bool:
    """
    Return True if the given gate type's Boolean function is invariant under
    arbitrary permutation of its fanin operands. This is used by
    symmetry_breaking.py to decide whether fanin-ordering symmetry-breaking
    clauses may be safely applied to a gate slot assigned this type.

    INV (arity 1) is trivially commutative. NAND2, NOR2, AND2, NAND3, NAND4
    are fully symmetric in all their operands. OAI21's function
    !((a | b) & c) is symmetric in (a, b) but NOT symmetric with respect to
    c, so OAI21 is only *partially* commutative (over its first two
    operands only); this function reports the *full*-symmetry property and
    returns False for OAI21, while `commutative_operand_groups` below
    reports the exact partial symmetry structure needed for correct,
    solution-preserving symmetry breaking.
    """
    spec = GATE_LIBRARY[gate_type]
    if spec.arity <= 1:
        return True
    import itertools

    fanin_indices = range(spec.arity)
    reference = spec.truth_table
    for perm in itertools.permutations(fanin_indices):
        permuted_table = []
        for index in range(1 << spec.arity):
            original_fanins = tuple((index >> j) & 1 for j in range(spec.arity))
            permuted_fanins = [0] * spec.arity
            for pos, original_pos in enumerate(perm):
                permuted_fanins[original_pos] = original_fanins[pos]
            permuted_index = 0
            for j, v in enumerate(permuted_fanins):
                permuted_index |= (v & 1) << j
            permuted_table.append(reference[permuted_index])
        if tuple(permuted_table) != reference:
            return False
    return True


def commutative_operand_groups(gate_type: GateType) -> tuple[tuple[int, ...], ...]:
    """
    Return a partition of the gate's fanin-position indices (0-based, in
    canonical fanin order) into groups such that fanin positions within the
    same group may be freely permuted without changing the gate's Boolean
    function, while fanin positions in different groups may not be
    interchanged. This exact structural information is what
    symmetry_breaking.py uses to emit fanin-ordering clauses that are sound
    (never eliminate every model of a satisfiable instance).

    Results (derived mechanically below, not hard-coded per gate):
        INV    : ((0,),)                         -- single operand, trivial
        NAND2  : ((0, 1),)                        -- fully symmetric pair
        NOR2   : ((0, 1),)                        -- fully symmetric pair
        AND2   : ((0, 1),)                        -- fully symmetric pair
        NAND3  : ((0, 1, 2),)                     -- fully symmetric triple
        NAND4  : ((0, 1, 2, 3),)                  -- fully symmetric quad
        OAI21  : ((0, 1), (2,))                   -- (a, b) interchangeable,
                                                      c is distinguished
    """
    spec = GATE_LIBRARY[gate_type]
    arity = spec.arity
    if arity <= 1:
        return (tuple(range(arity)),)

    # Union-Find over fanin positions: two positions are joined if swapping
    # them (holding all other positions fixed) leaves the truth table
    # invariant for every possible assignment of the remaining positions.
    parent = list(range(arity))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    reference = spec.truth_table
    for i in range(arity):
        for j in range(i + 1, arity):
            swap_invariant = True
            for index in range(1 << arity):
                fanins = [(index >> k) & 1 for k in range(arity)]
                swapped = list(fanins)
                swapped[i], swapped[j] = swapped[j], swapped[i]
                swapped_index = 0
                for k, v in enumerate(swapped):
                    swapped_index |= (v & 1) << k
                if reference[swapped_index] != reference[index]:
                    swap_invariant = False
                    break
            if swap_invariant:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for pos in range(arity):
        root = find(pos)
        groups.setdefault(root, []).append(pos)

    return tuple(tuple(sorted(g)) for g in sorted(groups.values(), key=lambda g: g[0]))
