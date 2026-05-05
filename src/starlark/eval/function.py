"""User-defined functions: `def` and `lambda`.

Phase 10 expands argument binding (kwargs, *args, **kwargs, defaults). For
now we provide just enough surface for the evaluator to run simple defs
and lambdas with positional and keyword arguments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..syntax import ast
from ..syntax.location import Position
from .errors import EvalError


@dataclass(slots=True, eq=False)  # identity equality + hash
class StarlarkFunction:
    """A user-defined function — produced by a `def` or `lambda` expression."""

    name: str
    params: list[ast.Parameter]
    body_stmts: list[ast.Statement] | None  # for def
    body_expr: ast.Expression | None  # for lambda
    # The AST node this function was created from. Used to detect recursion
    # by *syntactic* identity (two closures from the same lambda are
    # considered the same function for recursion-check purposes — see the
    # spec's section on Y combinator).
    ast_node: ast.DefStatement | ast.LambdaExpression | None = None
    defaults: dict[str, Any] = field(default_factory=dict)
    # Closure environment: a dict of free-variable name -> the dict-cell that
    # holds its value. We keep it as a flat mapping name -> dict (the
    # enclosing frame's env). Reads and writes go through this dict.
    closure: dict[str, dict] = field(default_factory=dict)
    # Source location for error messages.
    position: Position | None = None
    # Resolved info from the AST node, for the evaluator's frame setup.
    locals: tuple[str, ...] = ()
    freevars: tuple[str, ...] = ()

    _starlark_type = "function"

    def __repr__(self) -> str:
        return f"<function {self.name}>"


def bind_arguments(
    fn: StarlarkFunction,
    positional: list,
    keyword: dict,
) -> dict:
    """Match call-site arguments against `fn`'s parameter list.

    Returns a fresh dict of {param_name: value} for the new frame's locals.
    Raises EvalError on arity / keyword issues.
    """
    locals_: dict[str, Any] = {}
    # Classify parameters.
    star_param: str | None = None  # name of *args parameter, or None
    starstar_param: str | None = None
    positional_names: list[str] = []
    keyword_only: list[str] = []
    seen_star = False

    for p in fn.params:
        if isinstance(p, ast.MandatoryParameter):
            if seen_star:
                keyword_only.append(p.name.name)
            else:
                positional_names.append(p.name.name)
        elif isinstance(p, ast.OptionalParameter):
            if seen_star:
                keyword_only.append(p.name.name)
            else:
                positional_names.append(p.name.name)
        elif isinstance(p, ast.StarParameter):
            seen_star = True
            if p.name is not None:
                star_param = p.name.name
        elif isinstance(p, ast.StarStarParameter):
            starstar_param = p.name.name

    # Bind positionals.
    extra_positional: list = []
    for i, value in enumerate(positional):
        if i < len(positional_names):
            locals_[positional_names[i]] = value
        elif star_param is not None or seen_star:
            extra_positional.append(value)
        else:
            raise EvalError(
                f"function {fn.name} accepts {len(positional_names)} positional "
                f"arguments but {len(positional)} were given"
            )

    if star_param is not None:
        locals_[star_param] = tuple(extra_positional)
    elif extra_positional and seen_star:
        # Bare `*` separator with no name; extras still become an error.
        raise EvalError(f"function {fn.name} got unexpected positional arguments")

    # Bind keyword arguments.
    leftover_kw: dict[str, Any] = {}
    for kname, kvalue in keyword.items():
        if kname in positional_names or kname in keyword_only:
            if kname in locals_:
                raise EvalError(f"function {fn.name} got multiple values for argument {kname!r}")
            locals_[kname] = kvalue
        else:
            leftover_kw[kname] = kvalue

    if starstar_param is not None:
        from .mutability import Mutability
        from .values import Dict  # local import to avoid cycle

        # The kwargs dict is mutable but local to the call.
        m = Mutability("**kwargs")
        locals_[starstar_param] = Dict(leftover_kw, m)
    elif leftover_kw:
        names = ", ".join(sorted(leftover_kw))
        raise EvalError(f"function {fn.name} got unexpected keyword argument(s): {names}")

    # Apply defaults for any missing optional params.
    for p in fn.params:
        if isinstance(p, ast.OptionalParameter):
            if p.name.name not in locals_:
                locals_[p.name.name] = fn.defaults.get(p.name.name)

    # Validate that all mandatory positional/keyword-only params got values.
    for p in fn.params:
        if isinstance(p, ast.MandatoryParameter):
            if p.name.name not in locals_:
                raise EvalError(f"function {fn.name} missing required argument {p.name.name!r}")

    return locals_


__all__ = ["StarlarkFunction", "bind_arguments"]
