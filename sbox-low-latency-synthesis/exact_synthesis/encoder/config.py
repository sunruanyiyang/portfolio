"""
config.py

Global configuration for the SAT-based exact logic synthesis engine.

This module centralizes every constant that parameterizes the synthesis run:
the target Boolean function, the number of primary inputs, the delay
discretization granularity, default search bounds, gate-count sweep bounds,
and SAT solver options. No other module should hard-code these values; they
must all be imported from here so that a single, consistent configuration is
shared across the entire pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final


# --------------------------------------------------------------------------
# Target function specification
# --------------------------------------------------------------------------

#: Number of primary input variables (x0 .. x5).
NUM_INPUTS: Final[int] = 6

#: Number of minterms / input patterns for NUM_INPUTS boolean variables.
NUM_MINTERMS: Final[int] = 1 << NUM_INPUTS  # 64

#: Target truth table, given as a 64-bit hexadecimal literal.
#:
#: Bit convention: bit i of TARGET_TRUTH_TABLE_HEX (i = 0 .. 63) is the value
#: of the target function y0 evaluated at the input assignment whose binary
#: representation of i, read as (x5 x4 x3 x2 x1 x0) from MSB to LSB, assigns
#: x0 = bit 0 of i, x1 = bit 1 of i, ..., x5 = bit 5 of i. This is the
#: standard "little-endian minterm index" convention used throughout
#: truth_table.py.
TARGET_TRUTH_TABLE_HEX: Final[str] = "0x45D3356F02C1D7D8"

#: Integer value of the target truth table, parsed once here for convenience.
TARGET_TRUTH_TABLE_INT: Final[int] = int(TARGET_TRUTH_TABLE_HEX, 16)

#: Human-readable name of the single output signal being synthesized.
OUTPUT_NAME: Final[str] = "y0"

#: Names of the primary input signals, in index order (index 0 -> x0, etc.).
INPUT_NAMES: Final[tuple[str, ...]] = tuple(f"x{i}" for i in range(NUM_INPUTS))


# --------------------------------------------------------------------------
# Delay discretization
# --------------------------------------------------------------------------

#: All gate delays in this project are given in picoseconds as non-integer
#: floating point values (e.g. 27.886). SAT-based threshold/order encodings
#: require a discrete, totally ordered set of delay "levels". We therefore
#: discretize picoseconds into integer units by multiplying every delay by
#: DELAY_SCALE and rounding to the nearest integer.
#:
#: DELAY_SCALE DIRECTLY CONTROLS SOLVER PERFORMANCE: the number of distinct
#: reachable delay levels within any search window scales roughly linearly
#: with DELAY_SCALE, and delay clause count scales roughly linearly with
#: that level count. Measured for this project's 27-gate/13-gate-type
#: library over a 0-190ps window:
#:     DELAY_SCALE=100 (0.01ps resolution): 3,026 reachable levels
#:     DELAY_SCALE=10  (0.1ps resolution):    927 reachable levels
#:     DELAY_SCALE=1   (1ps resolution):       142 reachable levels  <- current
#: Going from 100 to 1 cuts delay clauses roughly 21x (from ~14.4M to
#: ~700k for this project's actual search), which is the difference between
#: multi-hour and tractable Kissat runs.
#:
#: TRADEOFF: DELAY_SCALE=1 rounds each gate's delay to the nearest whole
#: picosecond (max 0.5ps error per gate). Over a realistic critical path
#: depth of ~6-10 gates for this project's target function, worst-case
#: accumulated rounding is a few ps -- small relative to a 40ps search
#: window, and negligible next to the ~171-175ps values already confirmed
#: by known-good witness circuits. If ps-exact optimality matters more than
#: solve time, raise this back to 10 (0.1ps, ~3.3x fewer levels than the
#: original 100) as a middle ground, or 100 for the original exact scale.
DELAY_SCALE: Final[int] = 1

#: Maximum number of discrete delay levels considered during search. This is
#: a hard ceiling used to size the unary threshold-encoding arrays; it must
#: be at least as large as the maximum delay bound * DELAY_SCALE. For a 200 ps
#: upper bound, we need 200 * 1000 = 200000 levels. We allocate conservatively.
#: NOTE: This directly impacts SAT variable count (num_nodes * MAX_DELAY_LEVELS).
#: For typical S-box synthesis, 256000 is sufficient.
MAX_DELAY_LEVELS: Final[int] = 256000


def ps_to_level(delay_ps: float) -> int:
    """
    Convert a delay value given in picoseconds into an integer discrete
    delay "level" using DELAY_SCALE, rounding to the nearest integer level.

    This conversion is used uniformly for gate delays, and for the
    lower/upper search bounds supplied on the command line (which are also
    expressed in picoseconds for user convenience).
    """
    return int(round(delay_ps * DELAY_SCALE))


def level_to_ps(level: int) -> float:
    """
    Convert an integer discrete delay level back into a picosecond value,
    the exact inverse of ps_to_level (up to floating point representation).
    """
    return level / DELAY_SCALE


# --------------------------------------------------------------------------
# Gate count / circuit size bounds
# --------------------------------------------------------------------------

#: Default minimum number of internal gate slots attempted during the
#: gate-count sweep in search.py. A single-output function of 6 variables
#: can, in principle, be realized with as few as 1 gate if the target
#: function happens to be expressible directly by a library primitive, so we
#: start the sweep at 1.
MIN_GATE_BUDGET: Final[int] = 1

#: Default maximum number of internal gate slots attempted during the
#: gate-count sweep. This is a practical ceiling: for a 6-input function
#: with no XOR primitive, exact synthesis frequently requires a moderate
#: number of gates, but graduate-level exact-synthesis literature for
#: 6-input, single-output functions under restricted libraries typically
#: does not require more than a low double-digit number of gates. This may
#: be overridden from the command line.
MAX_GATE_BUDGET: Final[int] = 12

#: Maximum fanin arity across the entire gate library (NAND4 has arity 4).
#: Used to size fanin-selection variable arrays.
MAX_GATE_ARITY: Final[int] = 4


# --------------------------------------------------------------------------
# Search bounds (picoseconds), used as defaults if not overridden by the CLI
# --------------------------------------------------------------------------

#: Default lower bound (inclusive) on achievable critical path delay, in
#: picoseconds. Zero is always a mathematically valid, conservative lower
#: bound (no real circuit has negative delay), and is used to seed the
#: binary search.
DEFAULT_LOWER_BOUND_PS: Final[float] = 0.0

#: Default upper bound (inclusive) on achievable critical path delay, in
#: picoseconds, used to seed the binary search before any solve has been
#: attempted. This value is chosen generously: it comfortably exceeds the
#: maximum possible critical path length using MAX_GATE_BUDGET gates, each
#: contributing at most the single largest delay constant in the library.
DEFAULT_UPPER_BOUND_PS: Final[float] = 600.0


# --------------------------------------------------------------------------
# SAT solver configuration
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SolverConfig:
    """
    Configuration options forwarded to the PySAT Cadical103 solver wrapper
    in solver.py.
    """

    #: Name of the PySAT solver backend to instantiate. This project is
    #: pinned to Cadical103 as mandated by the project specification.
    solver_name: str = "cadical103"

    #: Whether to enable the solver's internal model-tracking / proof
    #: bookkeeping features that are unnecessary for pure SAT/UNSAT +
    #: model-extraction use, kept False for performance.
    with_proof: bool = False

    #: Whether solver.py should use PySAT's incremental assumption-based
    #: solving interface (solving under a set of unit assumption literals)
    #: rather than re-instantiating the solver and rebuilding the full
    #: clause database from scratch for every candidate delay bound tested
    #: during binary search. Cadical103 does not support incremental mode in
    #: PySAT, so this must remain False.
    use_incremental_assumptions: bool = False

    #: Verbosity level forwarded directly to the underlying solver.
    verbosity: int = 0


#: Module-level default solver configuration instance, importable directly.
DEFAULT_SOLVER_CONFIG: Final[SolverConfig] = SolverConfig()


# --------------------------------------------------------------------------
# Aggregate run configuration
# --------------------------------------------------------------------------

@dataclass
class RunConfig:
    """
    Aggregate configuration object threading together every parameter that
    a single end-to-end synthesis run (as orchestrated by main.py /
    search.py) needs. Individual fields default to the module-level
    constants above but may be overridden (e.g. from CLI arguments in
    main.py) without mutating global state.
    """

    num_inputs: int = NUM_INPUTS
    target_truth_table_int: int = TARGET_TRUTH_TABLE_INT
    output_name: str = OUTPUT_NAME
    input_names: tuple[str, ...] = field(default_factory=lambda: INPUT_NAMES)

    delay_scale: int = DELAY_SCALE
    max_delay_levels: int = MAX_DELAY_LEVELS

    min_gate_budget: int = MIN_GATE_BUDGET
    max_gate_budget: int = MAX_GATE_BUDGET
    max_gate_arity: int = MAX_GATE_ARITY

    lower_bound_ps: float = DEFAULT_LOWER_BOUND_PS
    upper_bound_ps: float = DEFAULT_UPPER_BOUND_PS

    solver_config: SolverConfig = field(default_factory=lambda: DEFAULT_SOLVER_CONFIG)

    def lower_bound_level(self) -> int:
        """Lower search bound expressed as a discrete delay level."""
        return ps_to_level(self.lower_bound_ps)

    def upper_bound_level(self) -> int:
        """Upper search bound expressed as a discrete delay level."""
        return ps_to_level(self.upper_bound_ps)