"""Predeclared builtins for the Bazel-style conformance suite.

These match Bazel's `net.starlark.java.eval.ScriptTest`.
Conformance .star files use them as predeclared globals (not via load()).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .builtins import _call_starlark
from .errors import EvalError
from .values import (
    BuiltinFunction,
    equal,
    repr_starlark,
)


@dataclass
class _Reporter:
    """Collects reported errors. assert_eq/assert_ append; assert_fails uses for matching."""

    errors: list[str] = field(default_factory=list)


# Per-thread reporter; mirrors the Java ScriptTest's StarlarkThread.threadLocal.
_REPORTERS: list[_Reporter] = []


def push_reporter() -> _Reporter:
    r = _Reporter()
    _REPORTERS.append(r)
    return r


def pop_reporter() -> _Reporter:
    return _REPORTERS.pop()


def _report(msg: str) -> None:
    if _REPORTERS:
        _REPORTERS[-1].errors.append(msg)
    else:
        # No reporter registered; surface as an EvalError so the user sees it.
        raise EvalError(msg)


# ---------------------------------------------------------------- assertions


def b_assert_(cond: Any, msg: Any = "assertion failed") -> None:
    from .values import truth
    if not truth(cond):
        _report(f"assert_: {msg}")


def b_assert_eq(x: Any, y: Any) -> None:
    if not equal(x, y):
        _report(f"assert_eq: {repr_starlark(x)} != {repr_starlark(y)}")


def b_assert_fails(fn: Any, want_error: Any) -> None:
    if not isinstance(want_error, str):
        raise EvalError("assert_fails: second argument must be a string regex")
    try:
        pattern = re.compile(want_error)
    except re.error:
        raise EvalError(f"assert_fails: invalid regexp: {want_error}") from None
    try:
        _call_starlark(fn)
    except EvalError as e:
        if not pattern.search(e.message):
            _report(
                f"assert_fails: regex {want_error!r} did not match error: {e.message}"
            )
        return
    _report(
        f"assert_fails: evaluation succeeded unexpectedly (want match for {want_error!r})"
    )


# ---------------------------------------------------------------- struct


class Struct:
    """A simple record. `s.x` returns the field x. Field access goes via the
    evaluator's `_attr_get`, which special-cases anything with a `fields` dict.
    Mutable variants from `mutablestruct(...)` allow `s.x = v`.
    """

    __slots__ = ("_frozen", "fields")

    def __init__(self, fields: dict, frozen: bool = True) -> None:
        self.fields = fields
        self._frozen = frozen

    @property
    def _starlark_type(self) -> str:
        return "struct" if self._frozen else "mutablestruct"

    def __repr__(self) -> str:
        body = ", ".join(
            f"{k} = {repr_starlark(v)}" for k, v in self.fields.items()
        )
        prefix = "struct" if self._frozen else "mutablestruct"
        return f"{prefix}({body})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Struct):
            return NotImplemented
        if list(self.fields.keys()) != list(other.fields.keys()):
            return False
        for k, v in self.fields.items():
            if not equal(v, other.fields[k]):
                return False
        return True

    def __ne__(self, other: object) -> bool:
        eq = self.__eq__(other)
        return NotImplemented if eq is NotImplemented else not eq


def b_struct(**kwargs) -> Struct:
    return Struct(fields=dict(kwargs))


def b_mutablestruct(**kwargs) -> Struct:
    s = Struct(fields=dict(kwargs))
    s._frozen = False
    return s


def b_freeze(*args) -> Any:
    if not args:
        return None
    x = args[0]
    if hasattr(x, "mutability"):
        from .mutability import Mutability
        m = Mutability(x.mutability.name)
        m.freeze()
        x.mutability = m
        return x
    if isinstance(x, Struct):
        x._frozen = True
        return x
    raise EvalError(f"{type(x).__name__} value is not freezable")


def b_int_mul_slow(x: int, y: int) -> int:
    return x * y


# ---------------------------------------------------------------- registry


def make_predeclared() -> dict[str, Any]:
    pairs = [
        ("assert_", b_assert_),
        ("assert_eq", b_assert_eq),
        ("assert_fails", b_assert_fails),
        ("freeze", b_freeze),
        ("struct", b_struct),
        ("mutablestruct", b_mutablestruct),
        ("int_mul_slow", b_int_mul_slow),
    ]
    return {name: BuiltinFunction(name=name, impl=fn) for name, fn in pairs}


__all__ = [
    "Struct",
    "make_predeclared",
    "pop_reporter",
    "push_reporter",
]
