"""Public API surface tests.

Asserts that the names the host integration story documents are importable
from the top-level `starlark` package and from `starlark.values`. Also
exercises `to_value`/`from_value` round-trips for every primitive type
the host can pass through the evaluator.
"""

from __future__ import annotations

import datetime

import pytest

import starlark
from starlark import (
    IMMUTABLE,
    BuiltinFunction,
    Dict,
    EvalError,
    Mutability,
    Range,
    StarlarkList,
    StarlarkSet,
    StarlarkSyntaxError,
    StarlarkSyntaxException,
    UnsupportedTypeError,
    from_value,
    make_universal,
    to_value,
)

# --------------------------------------------------------------- imports


def test_top_level_names_are_exported():
    expected = {
        "AllocLimitExceeded",
        "BuiltinFunction",
        "Dict",
        "EvalError",
        "IMMUTABLE",
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
        "eval",
        "exec_file",
        "from_value",
        "make_universal",
        "to_value",
    }
    missing = expected - set(dir(starlark))
    assert not missing, f"missing from top-level starlark: {sorted(missing)}"


def test_values_submodule_re_exports():
    from starlark import values

    for name in (
        "Dict",
        "StarlarkList",
        "StarlarkSet",
        "Range",
        "BuiltinFunction",
        "Mutability",
        "IMMUTABLE",
        "to_value",
        "from_value",
        "UnsupportedTypeError",
    ):
        assert hasattr(values, name), name


# --------------------------------------------------------------- to_value


def test_to_value_scalars_passthrough():
    for v in (None, True, False, 0, 1, -3, 3.14, "hello", b"bytes"):
        assert to_value(v) is v


def test_to_value_datetime_passthrough():
    dt = datetime.datetime(2026, 5, 7, 12, 30, 45)
    d = datetime.date(2026, 5, 7)
    t = datetime.time(12, 30, 45)
    for v in (dt, d, t):
        assert to_value(v) is v


def test_to_value_dict_returns_starlark_dict():
    result = to_value({"a": 1, "b": 2})
    assert isinstance(result, Dict)
    assert result["a"] == 1
    assert result["b"] == 2


def test_to_value_list_returns_starlark_list():
    result = to_value([1, 2, 3])
    assert isinstance(result, StarlarkList)
    assert list(result) == [1, 2, 3]


def test_to_value_tuple_stays_tuple():
    result = to_value((1, 2, "x"))
    assert isinstance(result, tuple)
    assert result == (1, 2, "x")


def test_to_value_nested():
    py = {"a": [1, 2, {"nested": (3, 4)}], "b": None}
    sv = to_value(py)
    assert isinstance(sv, Dict)
    assert isinstance(sv["a"], StarlarkList)
    inner_dict = sv["a"][2]
    assert isinstance(inner_dict, Dict)
    assert inner_dict["nested"] == (3, 4)


def test_to_value_default_mutability_is_frozen():
    sv = to_value([1, 2, 3])
    with pytest.raises(EvalError, match="frozen"):
        sv.append(4)


def test_to_value_with_explicit_mutability_allows_mutation():
    mod = starlark.Module("test")
    sv = to_value([1, 2, 3], mutability=mod.mutability)
    sv.append(4)
    assert list(sv) == [1, 2, 3, 4]
    mod.freeze()
    with pytest.raises(EvalError, match="frozen"):
        sv.append(5)


def test_to_value_passes_through_starlark_values():
    inner = StarlarkList([1, 2, 3], mutability=IMMUTABLE)
    sv = to_value({"x": inner})
    assert sv["x"] is inner


def test_to_value_rejects_unknown_types():
    class Custom:
        pass

    with pytest.raises(UnsupportedTypeError, match="Custom"):
        to_value(Custom())


# --------------------------------------------------------------- from_value


def test_from_value_scalars_passthrough():
    for v in (None, True, 0, 1.5, "x", b"bytes"):
        assert from_value(v) is v or from_value(v) == v


def test_from_value_dict():
    sv = Dict({"a": 1, "b": 2})
    assert from_value(sv) == {"a": 1, "b": 2}


def test_from_value_list():
    sv = StarlarkList([1, 2, 3])
    assert from_value(sv) == [1, 2, 3]


def test_from_value_tuple_becomes_list():
    assert from_value((1, 2, 3)) == [1, 2, 3]


def test_from_value_range_becomes_list():
    assert from_value(Range(0, 5, 1)) == [0, 1, 2, 3, 4]


def test_from_value_set_raises():
    with pytest.raises(UnsupportedTypeError, match="set"):
        from_value(StarlarkSet([1, 2, 3]))


def test_from_value_rejects_builtin_function():
    with pytest.raises(UnsupportedTypeError):
        from_value(BuiltinFunction(name="x", impl=lambda: None))


def test_from_value_nested_round_trip():
    py = {"a": [1, 2, {"b": 3}], "c": None, "d": "str"}
    assert from_value(to_value(py)) == py


def test_from_value_tuple_inside_dict_becomes_list():
    sv = to_value({"k": (1, 2, 3)})
    assert from_value(sv) == {"k": [1, 2, 3]}


# --------------------------------------------------------------- naming


def test_starlark_syntax_error_aliases_dataclass():
    """StarlarkSyntaxError is the renamed dataclass; instances live on
    StarlarkSyntaxException.errors."""
    with pytest.raises(StarlarkSyntaxException) as exc:
        starlark.parse("def 1: pass")
    # Each entry is the SyntaxError dataclass — same type as
    # StarlarkSyntaxError exported from the top level.
    assert all(isinstance(err, StarlarkSyntaxError) for err in exc.value.errors)


def test_make_universal_returns_dict():
    u = make_universal()
    assert isinstance(u, dict)
    assert "len" in u
    assert "json" in u


def test_mutability_is_constructible():
    m = Mutability("test")
    assert not m.frozen
    m.freeze()
    assert m.frozen


# --------------------------------------------------------------- depth bounds


def test_to_value_rejects_deeply_nested_input():
    """Adversarial host-side input must abort cleanly, not crash with
    Python's RecursionError."""
    deep = []
    inner = deep
    for _ in range(1000):
        new = []
        inner.append(new)
        inner = new
    with pytest.raises(ValueError, match="too deeply nested"):
        to_value(deep)


def test_to_value_rejects_python_dict_cycle():
    """A Python dict that references itself would otherwise infinite-recurse."""
    d: dict = {}
    d["self"] = d
    with pytest.raises(ValueError, match="too deeply nested"):
        to_value(d)


def test_from_value_rejects_starlark_list_cycle():
    """A Starlark list that contains itself would otherwise infinite-recurse."""
    mod = starlark.Module("test")
    sv = StarlarkList([], mutability=mod.mutability)
    sv.append(sv)
    with pytest.raises(ValueError, match="too deeply nested or cyclic"):
        from_value(sv)


def test_from_value_rejects_deep_nesting():
    mod = starlark.Module("test")
    inner = StarlarkList([], mutability=mod.mutability)
    deep = inner
    for _ in range(1000):
        new = StarlarkList([], mutability=mod.mutability)
        new.append(deep)
        deep = new
    with pytest.raises(ValueError, match="too deeply nested or cyclic"):
        from_value(deep)
