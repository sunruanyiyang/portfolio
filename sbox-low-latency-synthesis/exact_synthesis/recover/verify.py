"""
verify.py

Standalone functional verification of synthesized circuits. Given an extracted
Circuit (from extract_model.py) and the target truth table, this module:

  1. Simulates the circuit on all 64 input patterns.
  2. Compares each output against the target truth table.
  3. Reports any mismatches (should be none if the SAT encoding is correct).

This is a brute-force Python-level simulator: for each of the 64 input
assignments, we evaluate each gate in topological order and check that the
final output matches the target function value at that minterm.

No external Verilog simulator is used; the verification is pure Python.
"""

from __future__ import annotations

from extract_model import Circuit
from gate_library import GATE_LIBRARY
from truth_table import all_minterms, input_assignment, target_output_bit


def simulate_circuit_on_minterm(circuit: Circuit, minterm: int) -> int:
    """
    Simulate the circuit on a single input minterm and return the output value (0 or 1).

    Args:
        circuit: The Circuit object to simulate.
        minterm: The minterm index (0..63 for a 6-input function).

    Returns:
        The Boolean output value (0 or 1) at this minterm.
    """
    # Extract input values for this minterm.
    inputs = input_assignment(minterm, circuit.num_inputs)

    # Initialize signal values: primary inputs are fixed.
    signals = {}
    for i in range(circuit.num_inputs):
        signals[i] = inputs[i]

    # Simulate each gate in topological order (gates are already in order).
    for gate in circuit.gates:
        gate_node_index = gate.node_index(circuit.num_inputs)
        gate_spec = GATE_LIBRARY[gate.gate_type]

        # Get fanin signal values.
        fanin_values = [signals[fanin_node] for fanin_node in gate.fanins]

        # Evaluate gate output.
        gate_output = gate_spec.evaluate(fanin_values)

        # Store gate output signal.
        signals[gate_node_index] = gate_output

    # Retrieve the output signal value.
    output_value = signals[circuit.output_node]

    return output_value


def verify_circuit_against_truth_table(
    circuit: Circuit,
    target_truth_table_int: int,
    num_inputs: int,
    verbose: bool = False,
) -> bool:
    """
    Verify the circuit against a target truth table by simulating all minterms.

    Args:
        circuit: The Circuit to verify.
        target_truth_table_int: The target truth table as a 64-bit integer.
        num_inputs: Number of primary inputs (should be 6 for this project).
        verbose: If True, print detailed mismatch information.

    Returns:
        True if all minterms match, False if any mismatch is found.
    """
    all_correct = True
    mismatch_count = 0

    for minterm in all_minterms(num_inputs):
        # Simulate circuit output.
        circuit_output = simulate_circuit_on_minterm(circuit, minterm)

        # Get target output.
        target_output = target_output_bit(minterm, target_truth_table_int)

        if circuit_output != target_output:
            if verbose or mismatch_count == 0:
                # Print first few mismatches in detail.
                inputs_str = "".join(str(b) for b in input_assignment(minterm, num_inputs))
                print(
                    f"  Mismatch at minterm {minterm:2d} (inputs {inputs_str}): "
                    f"got {circuit_output}, expected {target_output}"
                )
            all_correct = False
            mismatch_count += 1

    if mismatch_count > 0:
        if not verbose:
            print(f"  Total mismatches: {mismatch_count} / {1 << num_inputs}")
        return False

    return True


def print_circuit_truth_table(circuit: Circuit, num_inputs: int, verbose: bool = True) -> None:
    """
    Print the circuit's computed truth table (for debugging/comparison).

    Args:
        circuit: The Circuit to evaluate.
        num_inputs: Number of inputs.
        verbose: Whether to print verbose output.
    """
    if not verbose:
        return

    print("\nCircuit Truth Table (computed via simulation):")
    bits = []
    for minterm in all_minterms(num_inputs):
        output = simulate_circuit_on_minterm(circuit, minterm)
        bits.append(output)

    # Assemble as a 64-bit integer (little-endian minterm indexing).
    truth_int = 0
    for m, bit in enumerate(bits):
        truth_int |= (bit & 1) << m

    print(f"  Truth table: {hex(truth_int)}")

    # Print minterm-by-minterm summary (first 10 and last 10 only).
    print("  Minterms:")
    for m in list(range(10)) + list(range(num_inputs * 4 - 5, 1 << num_inputs)):
        if m < (1 << num_inputs):
            inputs_str = "".join(str(b) for b in input_assignment(m, num_inputs))
            output = bits[m]
            print(f"    m={m:2d} {inputs_str} -> {output}")
