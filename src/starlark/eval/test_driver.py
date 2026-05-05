"""Predeclared builtins for the Bazel-style conformance suite.

These match Bazel's `net.starlark.java.eval.ScriptTest`.
Conformance .star files use them as predeclared globals (not via load()).
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
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


# Per-context reporter. ContextVar isolates state per OS thread so concurrent
# conformance runs don't share a reporter; nested `with_reporter` blocks use
# `Token` save/restore.
_REPORTER: ContextVar[_Reporter] = ContextVar("starlark.test_driver.reporter")


def push_reporter() -> _Reporter:
    """Install a new reporter and return it. Pair with `pop_reporter`.

    The `Token` returned by `ContextVar.set` is stashed on the reporter so
    `pop_reporter` can restore the previous value. This makes nested push/pop
    safe under concurrent use from multiple OS threads (each thread has its
    own context).
    """
    r = _Reporter()
    r._token = _REPORTER.set(r)  # type: ignore[attr-defined]
    return r


def pop_reporter() -> _Reporter:
    """Restore the previous reporter and return the one being popped."""
    r = _REPORTER.get()
    _REPORTER.reset(r._token)  # type: ignore[attr-defined]
    return r


@contextmanager
def with_reporter(r: _Reporter | None = None):
    """Context manager form of push/pop_reporter. Thread-safe under nesting."""
    if r is None:
        r = _Reporter()
    token = _REPORTER.set(r)
    try:
        yield r
    finally:
        _REPORTER.reset(token)


def _report(msg: str) -> None:
    r = _REPORTER.get(None)
    if r is not None:
        r.errors.append(msg)
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
        # No-arg freeze: freeze the current module's mutability so all
        # values it owns become read-only. Used by the conformance suite
        # to test frozen-state behavior.
        from .builtins import _CURRENT_MUTABILITY
        m = _CURRENT_MUTABILITY.get(None)
        if m is not None:
            m.freeze()
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
    "with_reporter",
]
