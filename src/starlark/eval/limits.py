"""Centralized allocation-size guards.

Container-producing operations call into these helpers before allocating,
so that hostile inputs (`[1] * 10**12`, `list(range(2**60))`, ...) raise
a controlled `EvalError` instead of consuming the host's memory or
hanging until the OS OOM-kills the process.

These are *soft* limits, not the per-evaluation heap accounting that a
full sandbox would need. They prevent the worst single-allocation
mistakes; they do not bound total memory across many small allocations.
See `docs/threat-model.md` for the boundary this draws.
"""

from __future__ import annotations

from .errors import EvalError

# Cap on the number of elements a single allocation may produce. 16M
# elements is large enough for any realistic config but small enough to
# fail fast on accidental-or-malicious overflow.
MAX_CONTAINER_ELEMENTS = 1 << 24

# Hard cap on the bit-length of any Starlark integer. This is a deliberate
# DIVERGENCE FROM THE JAVA REFERENCE, which uses an unbounded BigInteger.
# Python's int is also arbitrary precision, so without a cap a hostile
# `x = 2` / `for i in range(64): x = x * x` squaring loop reaches a
# multi-gigabit integer in 64 cheap-looking steps and a single CPython
# multiply of two such operands burns unbounded CPU. 2^19 bits is ~158k
# decimal digits — far above any real configuration value — and bounds one
# multiply of two cap-sized operands to tens of milliseconds (Karatsuba, no
# FFT). The cap, not the coarse step counter, is what bounds per-op CPU.
MAX_INT_BITS = 1 << 19

# Cap on AST / call-stack nesting depth. The parser and evaluator each
# recurse into Python's call stack; deep input (a 5000-level-nested list
# literal, or a function whose body is a 5000-deep `if/elif/else`) would
# otherwise raise Python's RecursionError, which leaks Python frames in
# the traceback and isn't a clean EvalError. 256 matches the JSON
# decoder's depth cap; below Python's default recursion limit (1000)
# with comfortable headroom for our own dispatch frames.
MAX_NESTING_DEPTH = 256


def check_container_size(n: int, *, label: str = "elements") -> int:
    """Reject an allocation request larger than `MAX_CONTAINER_ELEMENTS`.

    Used at every site where a fresh container's final size is known
    before allocation: `list(iter)`, tuple/list/string concatenation,
    `sorted(iter)`, `dict(pairs)`, etc.
    """
    if n > MAX_CONTAINER_ELEMENTS:
        # Wording matches the Java reference's "excessive capacity requested".
        raise EvalError(f"excessive capacity requested: {n} {label}")
    return n


def check_int_bits(bits: int, *, label: str = "integer") -> None:
    """Reject an integer result whose magnitude exceeds `MAX_INT_BITS`.

    Called *before* computing a result whose size is known a priori, at the
    construction sites that can grow an int past the cap (multiply, left
    shift, add/subtract, `int()`, integer literals). Operations that cannot
    exceed the larger operand (`//`, `%`, `>>`, `&`, `|`, `^`, `abs`, unary
    `-`/`+`/`~`) preserve the invariant for free and are not checked.
    """
    if bits > MAX_INT_BITS:
        raise EvalError(f"{label} too large: {bits} bits exceeds limit of {MAX_INT_BITS}")


def check_repeat(factor: int, length: int, *, unit: str = "elements") -> None:
    """Reject a repeat (`x * N`) larger than the cap.

    Reports the factor and the repeated unit's length, so error messages
    match the Java reference: 'excessive repeat (3 * 1073741824 elements)'
    or 'got X for repeat, want value in signed 32-bit range' for very
    large factors.
    """
    n = factor * length
    if n > MAX_CONTAINER_ELEMENTS:
        if factor >= (1 << 31):
            raise EvalError(f"got {factor} for repeat, want value in signed 32-bit range")
        raise EvalError(f"excessive repeat ({length} * {factor} {unit})")


# --------------------------------------------------------------- alloc costs
#
# Approximate byte costs used by the charge-only heap counter. They are
# rough — exact CPython sizes depend on the build, compaction state, and
# small-int caching — and the counter is documented as cumulative
# allocation, not live-memory residency. Numbers calibrated from
# `sys.getsizeof` on a 64-bit CPython 3.11 build, rounded to round numbers
# so the constants are easy to reason about.

# Empty-container overhead. Includes the Python wrapper plus the
# underlying dict/list and the Mutability reference.
ALLOC_LIST_BASE = 64
ALLOC_DICT_BASE = 256
ALLOC_SET_BASE = 256
ALLOC_TUPLE_BASE = 56
ALLOC_RANGE = 56

# Per-element cost. dict and set entries are larger than list slots
# because each entry stores a hash + key + value (set uses a sentinel
# value, so equivalent overhead).
ALLOC_LIST_ELEM = 8
ALLOC_TUPLE_ELEM = 8
ALLOC_DICT_ENTRY = 56
ALLOC_SET_ENTRY = 56

# Strings have variable per-byte overhead; we charge a small fixed amount
# per character.
ALLOC_STRING_BASE = 48
ALLOC_STRING_PER_CHAR = 1

# Large ints are charged linearly by bit-length so a sequence of small
# growing operations (each well under MAX_INT_BITS) still accumulates against
# the heap counter. ~30 bits per 4-byte CPython limb, charged as bits // 8.
# bool/None/float remain uncharged (interned or near-zero per-instance cost).
ALLOC_INT_BASE = 24  # small-int header/overhead


def list_alloc(n: int) -> int:
    return ALLOC_LIST_BASE + ALLOC_LIST_ELEM * n


def tuple_alloc(n: int) -> int:
    return ALLOC_TUPLE_BASE + ALLOC_TUPLE_ELEM * n


def dict_alloc(n: int) -> int:
    return ALLOC_DICT_BASE + ALLOC_DICT_ENTRY * n


def set_alloc(n: int) -> int:
    return ALLOC_SET_BASE + ALLOC_SET_ENTRY * n


def string_alloc(n: int) -> int:
    return ALLOC_STRING_BASE + ALLOC_STRING_PER_CHAR * n


def int_alloc(bits: int) -> int:
    return ALLOC_INT_BASE + (bits // 8)


__all__ = [
    "ALLOC_DICT_BASE",
    "ALLOC_DICT_ENTRY",
    "ALLOC_INT_BASE",
    "ALLOC_LIST_BASE",
    "ALLOC_LIST_ELEM",
    "ALLOC_RANGE",
    "ALLOC_SET_BASE",
    "ALLOC_SET_ENTRY",
    "ALLOC_STRING_BASE",
    "ALLOC_STRING_PER_CHAR",
    "ALLOC_TUPLE_BASE",
    "ALLOC_TUPLE_ELEM",
    "MAX_CONTAINER_ELEMENTS",
    "MAX_INT_BITS",
    "check_container_size",
    "check_int_bits",
    "check_repeat",
    "dict_alloc",
    "int_alloc",
    "list_alloc",
    "set_alloc",
    "string_alloc",
    "tuple_alloc",
]
