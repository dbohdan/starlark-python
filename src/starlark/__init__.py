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
from .eval.evaluator import Thread, eval_file
from .eval.module import Module
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
    """
    expr = parse_expression(source, file=filename)
    universal = make_universal()
    universal.update(env)
    module = Module(filename)
    locs = Lexer(source, file=filename).locs
    thread = Thread(
        module=module,
        universal=universal,
        locs=locs,
        max_steps=max_steps,
        on_max_steps=on_max_steps,
        max_allocs=max_allocs,
        on_max_allocs=on_max_allocs,
    )
    # Wrap as an expression statement to evaluate via eval_file.
    from .syntax import ast as _ast

    file = _ast.StarlarkFile(
        file=filename,
        statements=[_ast.ExpressionStatement(start=expr.start, end=expr.end, expression=expr)],
        errors=[],
    )
    resolve(file, locs, universal=frozenset(universal))
    if file.errors:
        raise StarlarkSyntaxException(file.errors)
    from .eval.builtins import with_mutability, with_thread
    from .eval.evaluator import Frame, _eval_expr

    frame = Frame(locals_=module.globals, function_name="<expr>", module=module)
    thread.frames.append(frame)
    try:
        with with_mutability(module.mutability), with_thread(thread):
            return _eval_expr(expr, frame, thread)
    finally:
        thread.frames.pop()


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
    """
    file = parse(source, file=filename)
    locs = Lexer(source, file=filename).locs
    pre = predeclared or {}
    uni = make_universal()
    if universal:
        uni.update(universal)
    resolve(
        file,
        locs,
        predeclared=frozenset(pre),
        universal=frozenset(uni),
    )
    if file.errors:
        raise StarlarkSyntaxException(file.errors)
    module = Module(filename)
    thread = Thread(
        module=module,
        predeclared=pre,
        universal=uni,
        locs=locs,
        loader=loader,
        max_steps=max_steps,
        on_max_steps=on_max_steps,
        max_allocs=max_allocs,
        on_max_allocs=on_max_allocs,
    )
    from .eval.builtins import with_mutability, with_thread

    with with_mutability(module.mutability), with_thread(thread):
        eval_file(file, thread)
    # Expose the Thread so hosts can read `module.thread.steps` /
    # `.allocs` for cost reporting.
    module.thread = thread
    return module


__all__ = [
    "IMMUTABLE",
    "AllocLimitExceeded",
    "BuiltinFunction",
    "Dict",
    "EvalError",
    "Module",
    "Mutability",
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
    "eval",
    "exec_file",
    "from_value",
    "make_universal",
    "to_value",
]
