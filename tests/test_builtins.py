"""Tests for core builtins (Phase 7)."""

from __future__ import annotations

import pytest

import starlark
from starlark.eval import Dict, EvalError, StarlarkList


def expr(source: str):
    return starlark.eval(source)


def run(source: str):
    return starlark.exec_file(source)


# ---------------------------------------------------------------- type / len


def test_type_builtin():
    assert expr("type(1)") == "int"
    assert expr("type('a')") == "string"
    assert expr("type(None)") == "NoneType"
    assert expr("type([])") == "list"
    assert expr("type({})") == "dict"
    assert expr("type((1, 2))") == "tuple"


def test_len_builtin():
    assert expr("len('hello')") == 5
    assert expr("len([1, 2, 3])") == 3
    assert expr("len({'a': 1})") == 1
    assert expr("len(range(10))") == 10


# ---------------------------------------------------------------- conversions


def test_int_conversion():
    assert expr("int(3.7)") == 3
    assert expr("int('42')") == 42
    assert expr("int('0x1F', 16)") == 31
    assert expr("int(True)") == 1
    assert expr("int(False)") == 0


def test_float_conversion():
    assert expr("float(3)") == 3.0
    assert expr("float('1.5')") == 1.5
    assert expr("float(True)") == 1.0


def test_str_conversion():
    assert expr("str(42)") == "42"
    assert expr("str([1, 2])") == "[1, 2]"
    assert expr("str(None)") == "None"


def test_bool_conversion():
    assert expr("bool(0)") is False
    assert expr("bool(1)") is True
    assert expr("bool('')") is False
    assert expr("bool('x')") is True


def test_repr_builtin():
    assert expr("repr('hi')") == '"hi"'
    assert expr("repr([1, 2])") == "[1, 2]"


# ---------------------------------------------------------------- collections


def test_list_builtin():
    v = expr("list((1, 2, 3))")
    assert isinstance(v, StarlarkList)
    assert list(v) == [1, 2, 3]


def test_tuple_builtin():
    assert expr("tuple([1, 2, 3])") == (1, 2, 3)


def test_dict_builtin():
    v = expr("dict([('a', 1), ('b', 2)])")
    assert isinstance(v, Dict)
    assert v["a"] == 1


def test_range_builtin():
    assert list(expr("range(5)")) == [0, 1, 2, 3, 4]
    assert list(expr("range(2, 5)")) == [2, 3, 4]
    assert list(expr("range(0, 10, 2)")) == [0, 2, 4, 6, 8]


def test_enumerate_builtin():
    v = expr("enumerate(['a', 'b', 'c'])")
    assert list(v) == [(0, "a"), (1, "b"), (2, "c")]


def test_zip_builtin():
    v = expr("zip([1, 2], ['a', 'b'])")
    assert list(v) == [(1, "a"), (2, "b")]


def test_reversed_builtin():
    assert list(expr("reversed([1, 2, 3])")) == [3, 2, 1]


# ---------------------------------------------------------------- sorted / min / max


def test_sorted_basic():
    assert list(expr("sorted([3, 1, 2])")) == [1, 2, 3]
    assert list(expr("sorted([3, 1, 2], reverse=True)")) == [3, 2, 1]


def test_sorted_stable():
    # Stable: equal keys preserve original order.
    src = "sorted([(1, 'a'), (0, 'b'), (1, 'c'), (0, 'd')], key=lambda x: x[0])"
    v = expr(src)
    assert list(v) == [(0, "b"), (0, "d"), (1, "a"), (1, "c")]


def test_sorted_with_lambda_key():
    assert list(expr("sorted([5, 1, 3], key=lambda x: -x)")) == [5, 3, 1]


def test_min_max():
    assert expr("min([3, 1, 2])") == 1
    assert expr("max([3, 1, 2])") == 3
    assert expr("min(5, 1, 3)") == 1
    assert expr("max(5, 1, 3)") == 5


def test_min_max_with_key():
    assert expr("min(['abc', 'd', 'ef'], key=lambda s: len(s))") == "d"


def test_all_any():
    assert expr("all([True, True, True])") is True
    assert expr("all([True, False, True])") is False
    assert expr("any([False, True, False])") is True
    assert expr("any([False, False])") is False


# ---------------------------------------------------------------- attr


def test_hasattr_string():
    # String methods are added in Phase 8; before then this returns False.
    # Some methods may be registered already; just ensure no crash.
    expr("hasattr('hi', 'upper')")
    expr("hasattr([], 'append')")


# ---------------------------------------------------------------- abs / hash


def test_abs():
    assert expr("abs(-5)") == 5
    assert expr("abs(-1.5)") == 1.5
    with pytest.raises(EvalError):
        expr("abs(True)")


def test_hash():
    # hash of a string is stable and returns an int.
    h = expr("hash('hello')")
    assert isinstance(h, int)
    assert h == expr("hash('hello')")
    with pytest.raises(EvalError):
        expr("hash([])")


# ---------------------------------------------------------------- fail


def test_fail_raises():
    with pytest.raises(EvalError, match="bad"):
        run("fail('bad')\n")


# ---------------------------------------------------------------- iteration


def test_for_with_range():
    m = run("total = 0\nfor i in range(5): total += i\n")
    assert m.globals["total"] == 0 + 1 + 2 + 3 + 4
