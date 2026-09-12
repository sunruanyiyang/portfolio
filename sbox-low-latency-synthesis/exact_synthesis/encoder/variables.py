"""
cnf_variables.py - BINARY ENCODING WITH GLOBAL DECODER LAYER

Centralized SAT variable pool with binary-encoded fanin selection.
Introduces decoder layer to expose one-hot interface for downstream encoders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from config import MAX_GATE_ARITY, MAX_DELAY_LEVELS, NUM_INPUTS


@dataclass
class VariablePool:
    """Mutable allocator for fresh SAT variable indices."""

    _next_var_id: int = field(default=1, init=False)
    _description: Dict[int, str] = field(default_factory=dict, init=False)

    def fresh_var(self, description: str | None = None) -> int:
        """Allocate a fresh, unique SAT variable ID."""
        var_id = self._next_var_id
        self._next_var_id += 1
        if description is not None:
            self._description[var_id] = description
        return var_id

    def num_vars(self) -> int:
        """Return total variables allocated."""
        return self._next_var_id - 1

    def describe(self, var_id: int) -> str | None:
        """Look up semantic description of a variable."""
        return self._description.get(var_id)

    def all_descriptions(self) -> Dict[int, str]:
        """Return entire description dictionary."""
        return dict(self._description)


def _num_bits_required(n: int) -> int:
    """Return number of bits needed to represent values 0..n-1."""
    if n <= 1:
        return 0
    import math
    return math.ceil(math.log2(n))


def allocate_structure_variables(
    pool: VariablePool, num_gates: int, num_inputs: int = NUM_INPUTS, max_arity: int = MAX_GATE_ARITY
) -> "StructureVariables":
    """
    Pre-allocate all SAT variables for circuit structure.
    Uses binary-encoded fanin selection with global decoder layer.
    """
    from gate_library import GATE_TYPES_ORDERED

    gate_type_vars: dict[int, dict[int, int]] = {}
    fanin_binary_vars: dict[int, dict[int, list[int]]] = {}
    fanin_decoder_vars: dict[int, dict[int, dict[int, int]]] = {}
    output_binary_vars: dict[int, int] = {}
    output_decoder_vars: dict[int, int] = {}
    unused_vars: dict[int, int] = {}
    signal_vars: dict[int, dict[int, int]] = {}

    num_nodes = num_inputs + num_gates

    # Allocate gate type variables (one-hot per gate)
    for g in range(num_inputs, num_inputs + num_gates):
        gate_type_vars[g] = {}
        for gt in GATE_TYPES_ORDERED:
            var_id = pool.fresh_var(f"is_type[gate_{g - num_inputs}][{gt.name}]")
            gate_type_vars[g][int(gt)] = var_id

    # Allocate fanin binary variables
    num_fanin_bits = _num_bits_required(num_nodes)

    for g in range(num_inputs, num_inputs + num_gates):
        fanin_binary_vars[g] = {}
        for p in range(max_arity):
            fanin_binary_vars[g][p] = []
            for bit in range(num_fanin_bits):
                var_id = pool.fresh_var(f"fanin_bit[gate_{g - num_inputs}][pos_{p}][bit_{bit}]")
                fanin_binary_vars[g][p].append(var_id)

    # Allocate fanin decoder variables (one-hot per position, source node)
    for g in range(num_inputs, num_inputs + num_gates):
        fanin_decoder_vars[g] = {}
        for p in range(max_arity):
            fanin_decoder_vars[g][p] = {}
            for n in range(g):
                var_id = pool.fresh_var(f"fanin_decoder[gate_{g - num_inputs}][pos_{p}][node_{n}]")
                fanin_decoder_vars[g][p][n] = var_id

    # Allocate output binary variables
    num_output_bits = _num_bits_required(num_nodes)

    for bit in range(num_output_bits):
        var_id = pool.fresh_var(f"output_bit[{bit}]")
        output_binary_vars[bit] = var_id

    # Allocate output decoder variables (one-hot per output node)
    for n in range(num_nodes):
        var_id = pool.fresh_var(f"output_decoder[node_{n}]")
        output_decoder_vars[n] = var_id

    # Allocate unused gate variables
    for g in range(num_inputs, num_inputs + num_gates):
        var_id = pool.fresh_var(f"is_unused[gate_{g - num_inputs}]")
        unused_vars[g] = var_id

    # Allocate signal variables for minterms
    num_minterms = 1 << num_inputs
    for n in range(num_nodes):
        signal_vars[n] = {}
        for m in range(num_minterms):
            var_id = pool.fresh_var(f"signal[node_{n}][minterm_{m}]")
            signal_vars[n][m] = var_id

    return StructureVariables(
        gate_type_vars=gate_type_vars,
        fanin_binary_vars=fanin_binary_vars,
        fanin_decoder_vars=fanin_decoder_vars,
        output_binary_vars=output_binary_vars,
        output_decoder_vars=output_decoder_vars,
        unused_vars=unused_vars,
        signal_vars=signal_vars,
        num_inputs=num_inputs,
        num_gates=num_gates,
        num_fanin_bits=num_fanin_bits,
        num_output_bits=num_output_bits,
    )


@dataclass(frozen=True)
class StructureVariables:
    """Bundle of all SAT variables for circuit structure."""

    gate_type_vars: dict[int, dict[int, int]]
    fanin_binary_vars: dict[int, dict[int, list[int]]]
    fanin_decoder_vars: dict[int, dict[int, dict[int, int]]]
    output_binary_vars: dict[int, int]
    output_decoder_vars: dict[int, int]
    unused_vars: dict[int, int]
    signal_vars: dict[int, dict[int, int]]

    num_inputs: int
    num_gates: int
    num_fanin_bits: int
    num_output_bits: int

    def num_nodes(self) -> int:
        """Total number of nodes (inputs + gates)."""
        return self.num_inputs + self.num_gates


def allocate_delay_variables(
    pool: VariablePool, num_gates: int, num_inputs: int = NUM_INPUTS, max_delay_levels: int = MAX_DELAY_LEVELS
) -> "DelayVariables":
    """Pre-allocate delay threshold variables with lazy allocation."""

    at_vars: dict[int, dict[int, int]] = {}
    num_nodes = num_inputs + num_gates

    for n in range(num_nodes):
        at_vars[n] = {}

    return DelayVariables(at_vars=at_vars, num_inputs=num_inputs, num_gates=num_gates, max_delay_levels=max_delay_levels)


@dataclass(frozen=True)
class DelayVariables:
    """Bundle of arrival time threshold variables."""

    at_vars: dict[int, dict[int, int]]
    num_inputs: int
    num_gates: int
    max_delay_levels: int

    def num_nodes(self) -> int:
        """Total number of nodes."""
        return self.num_inputs + self.num_gates