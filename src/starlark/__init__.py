"""Pure-Python implementation of the Starlark configuration language."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .eval.builtins import make_universal
from .eval.errors import (
    AllocLimitExceeded,
    EvalError,
    ResourceLimitExceeded,
    StepLimitExceeded,
)
from .eval.evaluator import Thread
from .eval.module import Module
from .program import Program, compile
from .syntax import Lexer, parse, parse_expression, resolve
from .syntax.errors import StarlarkSyntaxException
from .syntax.errors import SyntaxError as StarlarkSyntaxError
from .values import (
    IMMUTABLE,
    BuiltinFunction,
    Dict,
    Mutability,
    Range,
    StarlarkList,
    StarlarkSet,
    UnsupportedTypeError,
    from_value,
    to_value,
)

__version__ = "0.0.0"


def eval(
    source: str,
    filename: str = "<expr>",
    *,
    max_steps: int | None = None,
    on_max_steps: Callable[[Thread], None] | None = None,
    max_allocs: int | None = None,
    on_max_allocs: Callable[[Thread], None] | None = None,
    **env: Any,
) -> Any:
    """Evaluate a Starlark expression and return the resulting value.

    Extra keyword args are added to the universal namespace, on top of the
    full set of core builtins (`len`, `range`, `print`, …).

    Resource limits (all default to unlimited):

    - `max_steps`: cap on the number of Starlark operations (statements,
      expression nodes, calls). Raises `StepLimitExceeded` when exceeded.
    - `on_max_steps`: optional callback invoked once when the step cap is
      reached, before `StepLimitExceeded` is raised.
    - `max_allocs`: cap on cumulative allocation in approximate bytes.
      Raises `AllocLimitExceeded` when exceeded.
    - `on_max_allocs`: optional callback invoked once when the alloc cap
      is reached, before `AllocLimitExceeded` is raised.

    Equivalent to `compile(source, mode="expression").eval(**env, ...)`.
    """
    return compile(source, filename=filename, mode="expression").eval(
        max_steps=max_steps,
        on_max_steps=on_max_steps,
        max_allocs=max_allocs,
        on_max_allocs=on_max_allocs,
        **env,
    )


def exec_file(
    source: str,
    filename: str = "<file>",
    *,
    predeclared: dict[str, Any] | None = None,
    universal: dict[str, Any] | None = None,
    loader: Callable[[str], Module] | None = None,
    max_steps: int | None = None,
    on_max_steps: Callable[[Thread], None] | None = None,
    max_allocs: int | None = None,
    on_max_allocs: Callable[[Thread], None] | None = None,
) -> Module:
    """Parse, resolve, and execute `source` as a Starlark file.

    Returns the populated `Module`. `loader` is an optional callable mapping
    a module path string (passed to `load(...)`) to a `Module`. Raises
    `StarlarkSyntaxException` for parse/resolve errors and `EvalError` for
    runtime errors.

    Resource limits (all default to unlimited):

    - `max_steps`: cap on the number of Starlark operations (statements,
      expression nodes, calls). Raises `StepLimitExceeded` when exceeded.
    - `on_max_steps`: optional callback invoked once when the step cap is
      reached, before `StepLimitExceeded` is raised.
    - `max_allocs`: cap on cumulative allocation in approximate bytes.
      Raises `AllocLimitExceeded` when exceeded. Charge-only — values
      that go out of scope are not refunded.
    - `on_max_allocs`: optional callback invoked once when the alloc cap
      is reached, before `AllocLimitExceeded` is raised.

    Equivalent to `compile(source, mode="file").exec(...)`.
    """
    return compile(source, filename=filename, mode="file").exec(
        predeclared=predeclared,
        universal=universal,
        loader=loader,
        max_steps=max_steps,
        on_max_steps=on_max_steps,
        max_allocs=max_allocs,
        on_max_allocs=on_max_allocs,
    )


__all__ = [
    "IMMUTABLE",
    "AllocLimitExceeded",
    "BuiltinFunction",
    "Dict",
    "EvalError",
    "Lexer",
    "Module",
    "Mutability",
    "Program",
    "Range",
    "ResourceLimitExceeded",
    "StarlarkList",
    "StarlarkSet",
    "StarlarkSyntaxError",
    "StarlarkSyntaxException",
    "StepLimitExceeded",
    "Thread",
    "UnsupportedTypeError",
    "__version__",
    "compile",
    "eval",
    "exec_file",
    "from_value",
    "make_universal",
    "parse",
    "parse_expression",
    "resolve",
    "to_value",
]
