"""Pure-Python implementation of the Starlark configuration language."""

from __future__ import annotations

__version__ = "0.0.0"


def eval(source: str, filename: str = "<expr>"):
    """Evaluate a Starlark expression and return the resulting Python value.

    This is a stub. The real implementation will land alongside the evaluator.
    """
    raise NotImplementedError("starlark.eval is not implemented yet")


__all__ = ["__version__", "eval"]
