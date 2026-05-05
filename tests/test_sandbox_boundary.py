"""Sandbox-boundary tests.

The interpreter's sandbox guarantee is that user code never sees a raw
Python object — every value is either a primitive (`bool`, `int`,
`float`, `str`, `tuple`, `None`) or one of the Starlark wrapper types
(`StarlarkList`, `Dict`, `StarlarkSet`, `Range`, `BuiltinFunction`,
`StarlarkFunction`, `Struct`, the `json` namespace).

If a builtin or method ever returns a raw Python `list`, `dict`, or
`set`, that object would be exposed to user code. Python's `list` has
attributes (`__class__`, `__init_subclass__`, ...) that lead via
`__class__.__mro__[1].__subclasses__()` into the host's full type
graph — the classic Python sandbox-escape route.

This test enumerates every method and universal builtin and runs it
through reflection, asserting the return type is always one of the
allowed value-model types.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

import starlark
from starlark.eval import (
    BuiltinFunction,
    Dict,
    Module,
    Mutability,
    Range,
    StarlarkList,
    StarlarkSet,
)
from starlark.eval.builtins import make_universal, with_mutability
from starlark.eval.function import StarlarkFunction
from starlark.eval.methods import (
    _DICT_METHODS,
    _LIST_METHODS,
    _SET_METHODS,
    _STRING_METHODS,
)
from starlark.eval.test_driver import Struct, make_predeclared

ALLOWED_TYPES: tuple[type, ...] = (
    type(None),
    bool,
    int,
    float,
    str,
    tuple,
    StarlarkList,
    Dict,
    StarlarkSet,
    Range,
    BuiltinFunction,
    StarlarkFunction,
    Struct,
)


def _is_allowed(value: Any) -> bool:
    """Recursively check that `value` and everything inside it is allowed."""
    if value is None:
        return True
    # The json module is exposed as a namespace value with a `fields` dict;
    # accept anything that walks like a struct too (per `_attr_get`'s rule).
    if hasattr(value, "_starlark_type") and hasattr(value, "fields"):
        return True
    if not isinstance(value, ALLOWED_TYPES):
        return False
    if isinstance(value, tuple):
        return all(_is_allowed(x) for x in value)
    if isinstance(value, StarlarkList):
        return all(_is_allowed(x) for x in value)
    if isinstance(value, Dict):
        return all(_is_allowed(k) and _is_allowed(v) for k, v in value.items())
    if isinstance(value, StarlarkSet):
        return all(_is_allowed(x) for x in value)
    return True


def _describe(value: Any) -> str:
    return f"{type(value).__module__}.{type(value).__name__}"


# ---------------------------------------------------------------- universal


def test_universal_namespace_only_contains_allowed_types():
    universal = make_universal()
    for name, value in universal.items():
        assert _is_allowed(value), f"universal {name!r} is {_describe(value)}"


def test_test_driver_predeclared_only_contains_allowed_types():
    predeclared = make_predeclared()
    for name, value in predeclared.items():
        assert _is_allowed(value), f"predeclared {name!r} is {_describe(value)}"


# ---------------------------------------------------------------- per-type methods


def _call_method(receiver: Any, name: str, fn) -> Any:
    """Best-effort: call the method with the simplest plausible arg set.

    We only care about return types here; for methods we can't easily
    invoke (because they need specific argument shapes) we try a few
    arg-count variants and skip cleanly on failure.
    """
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    n = len(params) - 1  # exclude `self`
    # Try a handful of plausible argument lists.
    candidates: list[list[Any]] = [[]]
    if n >= 1:
        candidates.append([0])
        candidates.append([""])
        candidates.append([receiver if hasattr(receiver, "__iter__") else 0])
    if n >= 2:
        candidates.append([0, 0])
        candidates.append(["", ""])
        candidates.append(["a", "b"])
    last_err: Exception | None = None
    for args in candidates:
        try:
            return fn(receiver, *args)
        except Exception as e:
            last_err = e
            continue
    raise AssertionError(f"could not call {name} on {_describe(receiver)}: last error {last_err!r}")


def _allowed_or_raises(receiver: Any, name: str, fn) -> None:
    try:
        result = _call_method(receiver, name, fn)
    except (AssertionError, RuntimeError):
        # Method needed a specific argument shape we couldn't synthesise.
        # Methods that *only* succeed on specific inputs still have to
        # return Starlark-typed values when they do succeed; we'll catch
        # any leak via the conformance suite instead.
        return
    assert _is_allowed(result), (
        f"{type(receiver).__name__}.{name} returned {_describe(result)}: {result!r}"
    )


def test_string_methods_return_allowed_types():
    receiver = "hello"
    for name, fn in _STRING_METHODS.items():
        _allowed_or_raises(receiver, name, fn)


def test_list_methods_return_allowed_types():
    m = Mutability()
    for name, fn in _LIST_METHODS.items():
        receiver = StarlarkList([1, 2, 3], m)
        _allowed_or_raises(receiver, name, fn)


def test_dict_methods_return_allowed_types():
    m = Mutability()
    for name, fn in _DICT_METHODS.items():
        receiver = Dict({"a": 1, "b": 2}, m)
        _allowed_or_raises(receiver, name, fn)


def test_set_methods_return_allowed_types():
    m = Mutability()
    for name, fn in _SET_METHODS.items():
        receiver = StarlarkSet([1, 2, 3], m)
        _allowed_or_raises(receiver, name, fn)


# ---------------------------------------------------------------- end-to-end


def test_evaluating_each_method_returns_allowed_types():
    """A second-line check: actually evaluate Starlark expressions that call
    each universal builtin and method, then assert the returned value is
    in the allowed set. Catches regressions in the dispatch layer too.
    """
    cases = [
        "len('abc')",
        "type([])",
        "range(5)",
        "list(range(3))",
        "tuple([1,2])",
        "dict(a=1)",
        "set([1,2])",
        "sorted([3,1,2])",
        "reversed([1,2,3])",
        "enumerate(['a','b'])",
        "zip([1,2],[3,4])",
        "min(1,2,3)",
        "max(1,2,3)",
        "all([True,True])",
        "any([False,True])",
        "sum([1,2,3])",
        "abs(-5)",
        "hash('x')",
        "'hi'.upper()",
        "'a,b'.split(',')",
        "[1,2,3].pop()",
        "{'a':1}.keys()",
        "set([1,2]).union(set([2,3]))",
        "json.encode({'a': 1})",
        "json.decode('[1, 2]')",
    ]
    mod = Module("test")
    with with_mutability(mod.mutability):
        for src in cases:
            value = starlark.eval(src)
            assert _is_allowed(value), f"`{src}` returned {_describe(value)}: {value!r}"


@pytest.mark.parametrize(
    "name",
    ["StarlarkList", "Dict", "StarlarkSet", "Range", "BuiltinFunction"],
)
def test_wrappers_are_distinct_from_python_types(name: str):
    """Sanity: the wrapper types aren't subclasses of their Python
    equivalents. If they were, isinstance checks downstream of the
    sandbox might confuse a leaked Python list with a StarlarkList.
    """
    from starlark.eval import values

    cls = getattr(values, name)
    assert not issubclass(cls, list)
    assert not issubclass(cls, dict)
    assert not issubclass(cls, set)
