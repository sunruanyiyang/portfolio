"""
dimacs_writer.py - STREAMING DIMACS CNF WRITER

Replaces PySAT's Cadical103.add_clause() as the destination for every
encoder's clause_sink callback. Writes clauses directly to a DIMACS CNF file
as they're generated, rather than accumulating them in a Python list or
handing them to an in-process solver.

DIMACS CNF format:

    c optional comment lines
    p cnf <num_vars> <num_clauses>
    1 -4 7 0
    -2 3 0
    ...

Each clause line is a list of nonzero signed integers (literals) terminated
by a trailing 0. The header line's num_clauses count must exactly match the
number of clause lines that follow -- which means naive streaming can't know
that count until encoding finishes. This writer handles that by writing
clauses to a temporary body file first, then, once the final count and
variable count are known, writing the real file as: header + body content.
This avoids holding the entire clause set in memory as Python lists (the
actual point of moving off PySAT's in-memory model for very large instances),
while still producing a single valid, spec-compliant DIMACS file.
"""

from __future__ import annotations

import os
import tempfile
from typing import Optional


class DimacsWriter:
    """
    Streaming DIMACS CNF writer. Usage:

        writer = DimacsWriter()
        encode_structure_constraints(pool, writer.add_clause, struct_vars)
        encode_function_constraints(pool, writer.add_clause, struct_vars, tt)
        encode_delay_constraints(pool, writer.add_clause, struct_vars, delay_vars, level)
        writer.finalize(num_vars=pool.num_vars(), output_path="problem.cnf")

    Clauses are written to a temporary body file as they arrive (so memory
    usage stays O(1) in the number of clauses, not O(clauses)), and only the
    header line requires knowing the final clause count, which is written
    once `finalize()` is called.
    """

    def __init__(self, dir: Optional[str] = None):
        # `dir` lets the caller place the temp body file next to the final
        # .cnf output (same filesystem), so the finalize()/os.replace step
        # never fails with EXDEV (cross-device link) when the system temp
        # directory lives on a different mount than the work directory
        # (e.g. tmpfs /tmp vs. a disk-backed project dir).
        self._tmp_fd, self._tmp_path = tempfile.mkstemp(
            prefix="dimacs_body_", suffix=".tmp", dir=dir
        )
        self._tmp_file = os.fdopen(self._tmp_fd, "w")
        self._num_clauses = 0
        self._max_var_seen = 0
        self._finalized = False

    def add_clause(self, clause: list[int]) -> None:
        """
        Append one clause (a list of nonzero signed literal integers) to the
        CNF. This is the exact callable signature every encode_* function in
        this project expects as its `clause_sink` argument -- so encoders
        need zero changes to target this writer instead of a solver.
        """
        if self._finalized:
            raise RuntimeError("Cannot add clauses after finalize() has been called.")
        if not clause:
            # An empty clause is a hard contradiction (always-false); DIMACS
            # permits it (a bare "0" line), so honor it rather than silently
            # dropping -- but this should never legitimately happen from a
            # correct encoder, so surface it loudly.
            raise ValueError(
                "Refusing to silently write an empty clause (unconditional "
                "contradiction) -- this indicates an encoder bug, not a "
                "legitimate CNF constraint."
            )
        for lit in clause:
            if lit == 0:
                raise ValueError(f"Clause contains literal 0, which is not valid: {clause}")
            self._max_var_seen = max(self._max_var_seen, abs(lit))
        self._tmp_file.write(" ".join(str(l) for l in clause))
        self._tmp_file.write(" 0\n")
        self._num_clauses += 1

    def num_clauses(self) -> int:
        return self._num_clauses

    def max_var_seen(self) -> int:
        """Largest variable index referenced by any clause added so far."""
        return self._max_var_seen

    def finalize(self, output_path: str, num_vars: Optional[int] = None) -> None:
        """
        Write the final, spec-compliant DIMACS file to `output_path`:
        header line first, then every clause appended so far.

        Args:
            output_path: destination .cnf file path.
            num_vars: total variable count for the "p cnf" header. If not
                supplied, defaults to the largest variable index actually
                referenced by any clause (safe, but should normally be
                supplied explicitly as pool.num_vars() so that variables
                allocated but never referenced by any clause are still
                accounted for -- e.g. this matters if a solver or downstream
                tool assumes variable IDs are contiguous from 1).
        """
        if self._finalized:
            raise RuntimeError("finalize() has already been called on this writer.")
        self._tmp_file.close()

        effective_num_vars = num_vars if num_vars is not None else self._max_var_seen

        with open(output_path, "w") as out, open(self._tmp_path, "r") as body:
            out.write(f"c Generated by dimacs_writer.py\n")
            out.write(f"p cnf {effective_num_vars} {self._num_clauses}\n")
            for line in body:
                out.write(line)

        os.remove(self._tmp_path)
        self._finalized = True

    def __del__(self):
        # Best-effort cleanup of the temp body file if finalize() was never
        # called (e.g. an exception aborted encoding partway through).
        try:
            if not self._finalized and hasattr(self, "_tmp_file"):
                self._tmp_file.close()
                if os.path.exists(self._tmp_path):
                    os.remove(self._tmp_path)
        except Exception:
            pass
