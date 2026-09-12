"""
run_kissat.py - INVOKE KISSAT AND PARSE ITS DIMACS-FORMAT RESULT

Runs the external `kissat` binary on a CNF file and parses its stdout:

    s SATISFIABLE
    v 1 -2 3 -4 ... 0
    v ... 0

or

    s UNSATISFIABLE

Kissat's `v` lines may wrap across multiple lines and are terminated by a
trailing 0, exactly like a DIMACS clause. This module has zero dependency
on PySAT -- it shells out to the real kissat binary and parses plain text.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class KissatResult:
    satisfiable: Optional[bool]   # True=SAT, False=UNSAT, None=indeterminate (timeout/error)
    model: dict[int, bool]        # variable_id -> value; empty if not SAT
    solve_time_s: float
    raw_stdout: str
    return_code: int


def find_kissat_binary(explicit_path: Optional[str] = None) -> str:
    """
    Locate the kissat executable. Checks, in order: an explicitly supplied
    path, then $PATH via shutil.which. Raises FileNotFoundError with a clear
    message (including build instructions) if not found -- this project
    intentionally does NOT bundle or auto-install kissat.
    """
    if explicit_path:
        return explicit_path
    found = shutil.which("kissat")
    if found:
        return found
    raise FileNotFoundError(
        "kissat binary not found on PATH. Build it from source:\n"
        "  git clone https://github.com/arminbiere/kissat.git\n"
        "  cd kissat && ./configure && make\n"
        "  # binary appears at build/kissat\n"
        "Then either add it to PATH or pass --kissat-path explicitly."
    )


def run_kissat(
    cnf_path: str,
    kissat_path: Optional[str] = None,
    timeout_s: Optional[float] = None,
    extra_args: Optional[list[str]] = None,
    stream_output: bool = True,
) -> KissatResult:
    """
    Run `kissat <cnf_path>` and parse the result.

    IMPORTANT: kissat prints a periodic one-line progress report (conflicts,
    restarts, MB used, etc.) to stdout THE WHOLE TIME it's searching, even at
    default verbosity -- but subprocess.run(capture_output=True) BUFFERS all
    of that until the process exits, so a caller watching the terminal sees
    nothing for the entire (possibly multi-hour) run and has no way to tell
    "actively working" apart from "silently hung". stream_output=True (the
    default) fixes this: stdout is read and printed line-by-line as kissat
    produces it, via subprocess.Popen, while still being accumulated for the
    final SAT/UNSAT + model parse below.

    Kissat's exit codes: 10 = SATISFIABLE, 20 = UNSATISFIABLE, other = error
    or timeout. The "s SATISFIABLE"/"s UNSATISFIABLE" status line is parsed
    as the primary signal (more robust across kissat versions than exit code).
    """
    binary = find_kissat_binary(kissat_path)
    args = [binary] + (extra_args or []) + [cnf_path]

    t0 = time.time()
    stdout_lines: list[str] = []

    try:
        proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,  # line-buffered
        )
        while True:
            if timeout_s is not None and (time.time() - t0) > timeout_s:
                proc.kill()
                proc.wait()
                elapsed = time.time() - t0
                return KissatResult(
                    satisfiable=None, model={}, solve_time_s=elapsed,
                    raw_stdout="".join(stdout_lines), return_code=-1,
                )
            line = proc.stdout.readline()
            if line == "" and proc.poll() is not None:
                break
            if line:
                stdout_lines.append(line)
                if stream_output:
                    print(line, end="", flush=True)
        return_code = proc.returncode
        elapsed = time.time() - t0
        stdout = "".join(stdout_lines)
    except FileNotFoundError:
        raise
    except Exception as e:
        elapsed = time.time() - t0
        return KissatResult(
            satisfiable=None, model={}, solve_time_s=elapsed,
            raw_stdout="".join(stdout_lines) + f"\n[run_kissat error: {e}]",
            return_code=-1,
        )

    satisfiable = _parse_status(stdout)
    model = _parse_model(stdout) if satisfiable else {}

    return KissatResult(
        satisfiable=satisfiable,
        model=model,
        solve_time_s=elapsed,
        raw_stdout=stdout,
        return_code=return_code,
    )


def run_kissat_portfolio(
    cnf_path: str,
    kissat_path: Optional[str] = None,
    timeout_s: Optional[float] = None,
    num_workers: int = 4,
    seeds: Optional[list[int]] = None,
    poll_interval_s: float = 20.0,
) -> KissatResult:
    """
    Run several independent kissat processes on the SAME CNF file in
    parallel, each with a different random seed, and return as soon as ANY
    ONE of them reaches a conclusive SAT/UNSAT result (killing the rest).

    WHY THIS HELPS WITHOUT TOUCHING THE ENCODING
    ===============================================
    SAT solver runtime has enormous variance across random seeds on hard
    combinatorial instances -- the same CNF can take minutes with one seed
    and many hours with another, because the solver's branching/restart
    heuristics explore the search tree in a different order each time. This
    is a well-known, safe way to get a real speedup on a genuinely hard
    instance without any risk of an encoding bug: every worker solves the
    EXACT SAME clauses, just with different internal search order, so
    correctness is identical to a single run -- only the odds of finishing
    sooner improve. If the underlying instance is UNSAT, all workers are
    equally validly proving the same fact; whichever finishes first is used.

    This is NOT a substitute for fixing the actual symmetry-breaking gap in
    the encoding (which would reduce total work, not just variance) -- it's
    a practical, zero-risk mitigation to apply right now.
    """
    binary = find_kissat_binary(kissat_path)
    if seeds is None:
        seeds = list(range(num_workers))

    t0 = time.time()
    log_paths = [f"{cnf_path}.worker{i}.log" for i in range(len(seeds))]
    procs = []
    for i, seed in enumerate(seeds):
        args = [binary, f"--seed={seed}", cnf_path]
        log_file = open(log_paths[i], "w")
        proc = subprocess.Popen(args, stdout=log_file, stderr=subprocess.STDOUT)
        procs.append((proc, log_file, seed))

    print(f"  [portfolio] launched {len(seeds)} kissat workers with seeds {seeds}", flush=True)

    winner = None
    try:
        while winner is None:
            time.sleep(poll_interval_s)
            elapsed = time.time() - t0

            if timeout_s is not None and elapsed > timeout_s:
                print(f"  [portfolio] timeout after {elapsed:.0f}s -- no worker finished", flush=True)
                break

            still_running = 0
            for i, (proc, log_file, seed) in enumerate(procs):
                ret = proc.poll()
                if ret is not None and winner is None:
                    log_file.flush()
                    with open(log_paths[i]) as f:
                        text = f.read()
                    sat = _parse_status(text)
                    if sat is not None:
                        winner = (i, seed, sat, text)
                        break
                elif ret is None:
                    still_running += 1

            if winner is None:
                print(f"  [portfolio] {elapsed:.0f}s elapsed, {still_running}/{len(seeds)} workers still running", flush=True)
    finally:
        for proc, log_file, seed in procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            log_file.close()
        for p in log_paths:
            try:
                os.remove(p)
            except OSError:
                pass

    elapsed = time.time() - t0
    if winner is None:
        return KissatResult(satisfiable=None, model={}, solve_time_s=elapsed, raw_stdout="", return_code=-1)

    i, seed, sat, text = winner
    print(f"  [portfolio] worker {i} (seed={seed}) finished first after {elapsed:.0f}s: "
          f"{'SAT' if sat else 'UNSAT'}", flush=True)
    model = _parse_model(text) if sat else {}
    return KissatResult(satisfiable=sat, model=model, solve_time_s=elapsed, raw_stdout=text, return_code=(10 if sat else 20))


def _parse_status(stdout: str) -> Optional[bool]:
    """Parse the 's SATISFIABLE' / 's UNSATISFIABLE' status line."""
    for line in stdout.splitlines():
        line = line.strip()
        if line == "s SATISFIABLE":
            return True
        if line == "s UNSATISFIABLE":
            return False
    return None


def _parse_model(stdout: str) -> dict[int, bool]:
    """
    Parse all 'v ...' lines into a variable_id -> bool dict. Kissat may
    split the model across several 'v' lines, each ending mid-clause except
    the last, which ends with a literal '0'. We just collect every integer
    token from every 'v' line and drop the trailing 0 sentinel(s).
    """
    literals: list[int] = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("v "):
            tokens = line[2:].split()
            for tok in tokens:
                val = int(tok)
                if val != 0:
                    literals.append(val)

    model: dict[int, bool] = {}
    for lit in literals:
        var_id = abs(lit)
        model[var_id] = lit > 0
    return model
