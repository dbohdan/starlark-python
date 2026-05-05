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
            raise EvalError(
                f"got {factor} for repeat, want value in signed 32-bit range"
            )
        raise EvalError(f"excessive repeat ({length} * {factor} {unit})")


__all__ = ["MAX_CONTAINER_ELEMENTS", "check_container_size", "check_repeat"]
