"""
truth_table.py

Utilities for representing, parsing, and evaluating the target Boolean
function's truth table, and for enumerating input minterms in the exact bit
convention used throughout the rest of the synthesis engine.

Bit convention (must be used consistently by every other module):

    For an input pattern index `m` in the range [0, 2**NUM_INPUTS - 1], the
    boolean value assigned to input variable `x_k` (k = 0 .. NUM_INPUTS - 1)
    under pattern `m` is bit `k` of `m`:

        x_k(m) = (m >> k) & 1

    The target function's value at pattern `m` is bit `m` of the 64-bit
    truth table integer:

        y0(m) = (TARGET_TRUTH_TABLE_INT >> m) & 1

This module performs no SAT encoding; it is a pure, dependency-free
functional and combinatorial utility layer consumed by function_encoder.py
(to build per-minterm CNF clauses) and by the standalone verification logic
integrated into main.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from config import NUM_INPUTS, NUM_MINTERMS, TARGET_TRUTH_TABLE_INT


def parse_truth_table(hex_or_int: str | int, num_inputs: int = NUM_INPUTS) -> int:
    """
    Parse a truth table specification given either as a hexadecimal string
    (with or without a leading "0x") or as a raw integer, and return it as a
    Python integer. Validates that the resulting integer fits within
    `2**(2**num_inputs)` bits, raising ValueError otherwise.
    """
    if isinstance(hex_or_int, int):
        value = hex_or_int
    else:
        text = hex_or_int.strip()
        if text.lower().startswith("0x"):
            value = int(text, 16)
        else:
            value = int(text, 16)

    num_minterms = 1 << num_inputs
    max_value = (1 << num_minterms) - 1
    if value < 0 or value > max_value:
        raise ValueError(
            f"Truth table value {value:#x} does not fit within "
            f"{num_minterms} bits (max {max_value:#x}) for {num_inputs} inputs."
        )
    return value


def input_assignment(minterm: int, num_inputs: int = NUM_INPUTS) -> tuple[int, ...]:
    """
    Decompose a minterm index into its individual Boolean input values,
    returned as a tuple `(x0, x1, ..., x_{num_inputs-1})` of 0/1 integers,
    using the bit convention documented at module level (bit k of the
    minterm index is the value of x_k).
    """
    if minterm < 0 or minterm >= (1 << num_inputs):
        raise ValueError(
            f"Minterm index {minterm} out of range for {num_inputs} inputs "
            f"(valid range 0..{(1 << num_inputs) - 1})."
        )
    return tuple((minterm >> k) & 1 for k in range(num_inputs))


def minterm_from_assignment(assignment: Sequence[int]) -> int:
    """
    Inverse of `input_assignment`: given a sequence of 0/1 values
    `(x0, x1, ..., x_{n-1})`, return the corresponding minterm index.
    """
    minterm = 0
    for k, bit in enumerate(assignment):
        if bit not in (0, 1):
            raise ValueError(f"Assignment values must be 0 or 1, got {bit!r} at index {k}.")
        minterm |= (bit & 1) << k
    return minterm


def target_output_bit(minterm: int, truth_table_int: int = TARGET_TRUTH_TABLE_INT) -> int:
    """
    Return the target function's Boolean output value (0 or 1) at the given
    minterm index, extracted as bit `minterm` of the truth table integer.
    """
    if minterm < 0 or minterm >= NUM_MINTERMS:
        raise ValueError(
            f"Minterm index {minterm} out of range 0..{NUM_MINTERMS - 1}."
        )
    return (truth_table_int >> minterm) & 1


def all_minterms(num_inputs: int = NUM_INPUTS) -> range:
    """Return the full range of valid minterm indices for `num_inputs` variables."""
    return range(1 << num_inputs)


def enumerate_truth_table(
    truth_table_int: int = TARGET_TRUTH_TABLE_INT, num_inputs: int = NUM_INPUTS
) -> list["TruthTableRow"]:
    """
    Materialize the full truth table as a list of `TruthTableRow` records,
    one per minterm, each carrying the minterm index, the decomposed input
    assignment, and the target output bit. Convenience wrapper primarily
    used by reporting/verification code and by function_encoder.py when it
    needs to iterate the complete table with fully decomposed inputs.
    """
    rows: list[TruthTableRow] = []
    for m in all_minterms(num_inputs):
        rows.append(
            TruthTableRow(
                minterm=m,
                inputs=input_assignment(m, num_inputs),
                output=target_output_bit(m, truth_table_int),
            )
        )
    return rows


@dataclass(frozen=True)
class TruthTableRow:
    """A single row of a fully materialized truth table."""

    minterm: int
    inputs: tuple[int, ...]
    output: int

    def input_str(self) -> str:
        """Render the input assignment as a compact binary string, x0 first."""
        return "".join(str(b) for b in self.inputs)


def format_truth_table(
    truth_table_int: int = TARGET_TRUTH_TABLE_INT,
    num_inputs: int = NUM_INPUTS,
    input_names: Sequence[str] | None = None,
) -> str:
    """
    Produce a human-readable, fixed-width textual dump of the full truth
    table, one line per minterm, formatted as:

        m=  0  x5x4x3x2x1x0=000000  y=1

    Intended for diagnostic/reporting output in main.py; not used by any
    CNF-encoding logic.
    """
    if input_names is None:
        input_names = [f"x{i}" for i in range(num_inputs)]

    header_names = "".join(reversed([input_names[i] for i in range(num_inputs)]))
    lines = [f"# minterm bit order (MSB..LSB): {header_names}"]
    for row in enumerate_truth_table(truth_table_int, num_inputs):
        bits_msb_first = "".join(str(b) for b in reversed(row.inputs))
        lines.append(f"m={row.minterm:3d}  inputs={bits_msb_first}  y={row.output}")
    return "\n".join(lines)


def truth_table_popcount(truth_table_int: int = TARGET_TRUTH_TABLE_INT) -> int:
    """
    Return the number of minterms for which the target function evaluates
    to 1 (the Hamming weight of the truth table). Useful as a quick sanity
    / reporting statistic.
    """
    return bin(truth_table_int).count("1")
