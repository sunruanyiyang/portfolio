"""
extract_model.py

Converts a satisfying SAT assignment (a dict mapping variable IDs to Boolean
values) back into a concrete circuit representation: a list of gate instances,
their types, fanin connections, and the selected primary output node.

This is the inverse of the encoding process: while structure_encoder.py and
function_encoder.py convert a circuit specification into CNF clauses, this
module converts a satisfying CNF assignment back into a human-readable circuit
description.

The extracted circuit is represented as a Circuit dataclass containing:
  - Gate instances (one per non-unused gate slot)
  - The primary output node index
  - Metadata about the circuit (number of inputs, etc.)

This Circuit object is then passed to export_verilog.py for netlist emission.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from variables import StructureVariables
from gate_library import GateType, GATE_TYPES_ORDERED, gate_spec
from structure_encoder import get_selected_fanins, get_selected_gate_type, get_selected_output


@dataclass(frozen=True)
class GateInstance:
    """Represents a single instantiated gate in the extracted circuit."""

    index: int  # Gate index (relative to first gate, 0-based)
    gate_type: GateType  # The gate's type
    fanins: list[int]  # Fanin node indices (in canonical order)

    def name(self) -> str:
        """Return a human-readable gate instance name (e.g., 'g0', 'g1', ...)."""
        return f"g{self.index}"

    def node_index(self, num_inputs: int) -> int:
        """Return the absolute node index for this gate in the full node space."""
        return num_inputs + self.index


@dataclass(frozen=True)
class Circuit:
    """
    A concrete circuit extracted from a satisfying SAT model. Contains all
    gates that were selected (unused gates are omitted) and the selected output.
    """

    num_inputs: int
    gates: tuple[GateInstance, ...]
    output_node: int

    def num_gates(self) -> int:
        """Return the number of non-unused gates."""
        return len(self.gates)

    def num_nodes(self) -> int:
        """Return the total number of nodes (inputs + gates)."""
        return self.num_inputs + self.num_gates()

    def output_is_primary_input(self) -> bool:
        """Return True if the selected output is a primary input."""
        return self.output_node < self.num_inputs

    def output_gate_index(self) -> int | None:
        """
        If the selected output is a gate, return its index (0-based, relative
        to the first gate). Otherwise, return None.
        """
        if self.output_is_primary_input():
            return None
        return self.output_node - self.num_inputs

    def get_gate(self, index: int) -> GateInstance | None:
        """Retrieve a gate by its index, or None if out of range."""
        if 0 <= index < len(self.gates):
            return self.gates[index]
        return None


def extract_circuit_from_model(
    struct_vars: StructureVariables, model: dict[int, bool]
) -> Circuit:
    """
    Given the structure-encoding variables and a satisfying SAT model,
    extract the concrete circuit description.

    Args:
        struct_vars: The StructureVariables allocated during encoding.
        model: A dict mapping variable IDs to Boolean values (from
               SATSolver.get_model()).

    Returns:
        A Circuit object representing the extracted circuit.

    Raises:
        RuntimeError if the model is inconsistent (e.g., multiple gate types
        selected for a single gate, which would indicate an encoding or
        extraction bug).
    """
    num_inputs = struct_vars.num_inputs
    num_gates = struct_vars.num_gates

    # Extract all non-unused gates in order.
    gates: list[GateInstance] = []
    for gate_index in range(num_gates):
        gate_type_int = get_selected_gate_type(struct_vars, model, gate_index)

        if gate_type_int is None:
            # This gate is marked unused; skip it.
            continue

        # Convert the integer gate type to the GateType enum.
        gate_type = GateType(gate_type_int)

        # Extract this gate's fanin connections.
        fanins = get_selected_fanins(struct_vars, model, gate_index)

        gate = GateInstance(index=len(gates), gate_type=gate_type, fanins=fanins)
        gates.append(gate)

    # Extract the selected primary output node.
    output_node = get_selected_output(struct_vars, model)

    return Circuit(
        num_inputs=num_inputs, gates=tuple(gates), output_node=output_node
    )


def circuit_to_netlist_text(circuit: Circuit, input_names: Sequence[str] | None = None) -> str:
    """
    Produce a human-readable textual description of the circuit, suitable for
    diagnostic output. This is NOT a Verilog netlist; it's a summary.

    Format:
        # Circuit Summary
        Inputs: 6 (x0, x1, x2, x3, x4, x5)
        Gates: 3
        Output: g1 (node 8)

        Gate Instances:
        g0: NAND2(x0, x1)
        g1: AND2(x2, g0)
        g2: NOR2(x5, g1)
    """
    if input_names is None:
        input_names = [f"x{i}" for i in range(circuit.num_inputs)]

    lines = [
        "# Circuit Summary",
        f"Inputs: {circuit.num_inputs} ({', '.join(input_names)})",
        f"Gates: {circuit.num_gates()}",
    ]

    if circuit.output_is_primary_input():
        output_name = input_names[circuit.output_node]
        lines.append(f"Output: {output_name} (primary input {circuit.output_node})")
    else:
        gate_idx = circuit.output_gate_index()
        lines.append(f"Output: g{gate_idx} (node {circuit.output_node})")

    lines.append("")
    lines.append("Gate Instances:")

    for gate in circuit.gates:
        gate_spec_obj = gate_spec(gate.gate_type)
        fanin_names = []
        for fanin_node in gate.fanins:
            if fanin_node < circuit.num_inputs:
                fanin_names.append(input_names[fanin_node])
            else:
                fanin_gate_idx = fanin_node - circuit.num_inputs
                fanin_names.append(f"g{fanin_gate_idx}")
        fanin_str = ", ".join(fanin_names)
        lines.append(f"{gate.name()}: {gate_spec_obj.name}({fanin_str})")

    return "\n".join(lines)


def verify_circuit_structure(circuit: Circuit, num_inputs: int) -> bool:
    """
    Perform basic structural sanity checks on the extracted circuit:
    - All gate fanins are valid node indices (< circuit.num_nodes()).
    - All fanins are strictly earlier than the gate's own node index
      (enforce acyclicity).
    - The output node is valid (< circuit.num_nodes()).

    Returns True if all checks pass, False otherwise (logs violations).
    """
    for gate in circuit.gates:
        gate_node = gate.node_index(circuit.num_inputs)
        for fanin_node in gate.fanins:
            if fanin_node >= gate_node:
                print(
                    f"ERROR: Gate {gate.name()} (node {gate_node}) has fanin "
                    f"node {fanin_node} that is not strictly earlier (violates acyclicity)."
                )
                return False
            if fanin_node < 0 or fanin_node >= circuit.num_nodes():
                print(
                    f"ERROR: Gate {gate.name()} (node {gate_node}) has fanin "
                    f"node {fanin_node} that is out of range [0, {circuit.num_nodes() - 1}]."
                )
                return False

    if circuit.output_node < 0 or circuit.output_node >= circuit.num_nodes():
        print(
            f"ERROR: Output node {circuit.output_node} is out of range "
            f"[0, {circuit.num_nodes() - 1}]."
        )
        return False

    return True
