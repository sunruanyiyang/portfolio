"""
export_verilog.py

Emits a synthesized circuit as a structural Verilog netlist using primitive
gate instantiations from the fixed gate library. The output is synthesizable
and human-readable, suitable for integration into larger designs or for
validation against the target truth table.

The netlist structure is:

    module synthesized_y0(
        input [5:0] x,
        output y
    );

    // Internal signal declarations
    wire g0, g1, g2, ...;

    // Gate instances (one per extracted gate)
    nand g0_inst(g0, x[0], x[1]);
    and g1_inst(g1, x[0], g0);
    ...

    // Output assignment
    assign y = (g_output | x_output);

    endmodule

Special handling for OAI21 (the only gate without a direct Verilog primitive):
    // For OAI21(a, b, c) = !((a | b) & c), use an assign statement
    wire oai21_out;
    assign oai21_out = ~((a | b) & c);
"""

from __future__ import annotations

from typing import Sequence, TextIO

from extract_model import Circuit, GateInstance
from gate_library import GATE_LIBRARY, GateType, gate_spec


def emit_verilog_header(
    output_file: TextIO,
    module_name: str,
    num_inputs: int,
    input_names: Sequence[str],
    output_name: str,
) -> None:
    """Emit the module header and port declarations."""
    output_file.write(f"module {module_name}(\n")
    output_file.write(f"  input [{num_inputs - 1}:0] x,\n")
    output_file.write(f"  output {output_name}\n")
    output_file.write(");\n\n")


def emit_verilog_internal_signals(
    output_file: TextIO, circuit: Circuit, num_inputs: int
) -> None:
    """Declare internal wires for gate outputs."""
    if circuit.num_gates() == 0:
        return

    output_file.write("  // Internal signals\n")
    for gate in circuit.gates:
        output_file.write(f"  wire {gate.name()};\n")
    output_file.write("\n")


def emit_gate_instance(
    output_file: TextIO,
    circuit: Circuit,
    gate: GateInstance,
    input_names: Sequence[str],
    instance_number: int,
) -> None:
    """Emit a single gate instantiation (or assign for special gates)."""
    spec = gate_spec(gate.gate_type)
    gate_name = spec.name
    output_name = gate.name()

    # Convert fanin node indices to signal names
    fanin_signals = []
    for fanin_node in gate.fanins:
        if fanin_node < circuit.num_inputs:
            fanin_signals.append(f"x[{fanin_node}]")
        else:
            gate_idx = fanin_node - circuit.num_inputs
            fanin_signals.append(f"g{gate_idx}")

    # Gates with no direct Verilog primitive are emitted as `assign`
    # statements using an explicit Boolean expression template, keyed by
    # gate name. Each template takes the ordered fanin signal names.
    ASSIGN_TEMPLATES = {
        "OAI21": lambda s: f"~(({s[0]} | {s[1]}) & {s[2]})",   # !((A1|A2)&B1)
        "AOI21": lambda s: f"~(({s[0]} & {s[1]}) | {s[2]})",   # !((A1&A2)|B1)
        "OAI22": lambda s: f"~(({s[0]} | {s[1]}) & ({s[2]} | {s[3]}))",  # !((A1|A2)&(B1|B2))
        "AOI22": lambda s: f"~(({s[0]} & {s[1]}) | ({s[2]} & {s[3]}))",  # !((A1&A2)|(B1&B2))
    }

    if gate_name in ASSIGN_TEMPLATES:
        expected_arity = spec.arity
        if len(fanin_signals) != expected_arity:
            raise ValueError(
                f"{gate_name} gate {output_name} has {len(fanin_signals)} fanins, "
                f"expected {expected_arity}."
            )
        expr = ASSIGN_TEMPLATES[gate_name](fanin_signals)
        output_file.write(
            f"  assign {output_name} = {expr}; "
            f"// {gate_name} (instance {instance_number})\n"
        )
    else:
        # Standard Verilog primitive
        if spec.verilog_op is None:
            raise ValueError(f"Gate {gate_name} has no Verilog primitive name.")

        fanin_list = ", ".join(fanin_signals)
        output_file.write(
            f"  {spec.verilog_op} {output_name}_inst({output_name}, {fanin_list}); "
            f"// {gate_name} (instance {instance_number})\n"
        )


def emit_verilog_gates(
    output_file: TextIO, circuit: Circuit, input_names: Sequence[str]
) -> None:
    """Emit all gate instantiations."""
    if circuit.num_gates() == 0:
        output_file.write("  // No gates (output is a primary input)\n\n")
        return

    output_file.write("  // Gate instances\n")
    for instance_num, gate in enumerate(circuit.gates):
        emit_gate_instance(output_file, circuit, gate, input_names, instance_num)
    output_file.write("\n")


def emit_verilog_output_assignment(
    output_file: TextIO, circuit: Circuit, input_names: Sequence[str], output_name: str
) -> None:
    """Emit the output assignment (mux to select primary output)."""
    if circuit.output_is_primary_input():
        # Output is a primary input
        input_idx = circuit.output_node
        output_file.write(f"  // Output is primary input x[{input_idx}]\n")
        output_file.write(f"  assign {output_name} = x[{input_idx}];\n")
    else:
        # Output is a gate
        gate_idx = circuit.output_gate_index()
        output_file.write(f"  // Output is gate g{gate_idx}\n")
        output_file.write(f"  assign {output_name} = g{gate_idx};\n")
    output_file.write("\n")


def emit_verilog_footer(output_file: TextIO) -> None:
    """Emit the module closing."""
    output_file.write("endmodule\n")


def export_circuit_to_verilog(
    circuit: Circuit,
    output_file: TextIO,
    module_name: str = "synthesized_y0",
    input_names: Sequence[str] | None = None,
    output_name: str = "y",
) -> None:
    """
    Export the extracted circuit as a complete, synthesizable Verilog module.

    Args:
        circuit: The Circuit object to export.
        output_file: An open file object (or stdout-like) to write to.
        module_name: The Verilog module name (default: "synthesized_y0").
        input_names: Names for the input ports (default: x0, x1, ...).
        output_name: Name for the output port (default: "y").
    """
    if input_names is None:
        input_names = [f"x{i}" for i in range(circuit.num_inputs)]

    emit_verilog_header(output_file, module_name, circuit.num_inputs, input_names, output_name)
    emit_verilog_internal_signals(output_file, circuit, circuit.num_inputs)
    emit_verilog_gates(output_file, circuit, input_names)
    emit_verilog_output_assignment(output_file, circuit, input_names, output_name)
    emit_verilog_footer(output_file)


def export_circuit_to_file(
    circuit: Circuit,
    filename: str,
    module_name: str = "synthesized_y0",
    input_names: Sequence[str] | None = None,
    output_name: str = "y",
) -> None:
    """
    Convenience wrapper: export the circuit to a named file.

    Args:
        circuit: The Circuit object to export.
        filename: Path to the output Verilog file.
        module_name: Verilog module name.
        input_names: Input port names.
        output_name: Output port name.
    """
    with open(filename, "w") as f:
        export_circuit_to_verilog(circuit, f, module_name, input_names, output_name)
