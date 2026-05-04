"""Pure-Python implementation of the Starlark configuration language."""

from __future__ import annotations

from typing import Any

from .eval.errors import EvalError
from .eval.evaluator import Thread, eval_file
from .eval.module import Module
from .syntax import Lexer, parse, parse_expression, resolve
from .syntax.errors import StarlarkSyntaxException

__version__ = "0.0.0"


def eval(source: str, filename: str = "<expr>", **env: Any) -> Any:
    """Evaluate a Starlark expression and return the resulting value.

    `env` provides predeclared/universal names. By default the universal set
    is empty except for None/True/False, which are special-cased.
    """
    expr = parse_expression(source, file=filename)
    universal = dict(env)
    module = Module(filename)
    locs = Lexer(source, file=filename).locs
    thread = Thread(module=module, universal=universal, locs=locs)
    # Wrap as an expression statement to evaluate via eval_file.
    from .syntax import ast as _ast
    file = _ast.StarlarkFile(
        file=filename,
        statements=[_ast.ExpressionStatement(start=expr.start, end=expr.end, expression=expr)],
        errors=[],
    )
    resolve(file, locs, universal=frozenset(env) | {"None", "True", "False"})
    if file.errors:
        raise StarlarkSyntaxException(file.errors)
    # eval_file's last statement value is not captured; use _eval_expr directly.
    from .eval.evaluator import Frame, _eval_expr
    frame = Frame(locals_=module.globals, function_name="<expr>", module=module)
    thread.frames.append(frame)
    try:
        return _eval_expr(expr, frame, thread)
    finally:
        thread.frames.pop()


def exec_file(
    source: str,
    filename: str = "<file>",
    *,
    predeclared: dict[str, Any] | None = None,
    universal: dict[str, Any] | None = None,
) -> Module:
    """Parse, resolve, and execute `source` as a Starlark file.

    Returns the populated `Module`. Raises `SyntaxError` for parse/resolve
    errors and `EvalError` for runtime errors.
    """
    file = parse(source, file=filename)
    locs = Lexer(source, file=filename).locs
    pre = predeclared or {}
    uni = universal or {}
    resolve(
        file,
        locs,
        predeclared=frozenset(pre),
        universal=frozenset(uni) | {"None", "True", "False"},
    )
    if file.errors:
        raise StarlarkSyntaxException(file.errors)
    module = Module(filename)
    thread = Thread(module=module, predeclared=pre, universal=uni, locs=locs)
    eval_file(file, thread)
    return module


__all__ = [
    "EvalError",
    "Module",
    "Thread",
    "__version__",
    "eval",
    "exec_file",
]
