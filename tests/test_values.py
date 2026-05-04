"""Tests for the value model and Mutability."""

from __future__ import annotations

import pytest

from starlark.eval import (
    Dict,
    EvalError,
    Module,
    Mutability,
    Range,
    StarlarkList,
    StarlarkSet,
    check_hashable,
    equal,
    less_than,
    repr_starlark,
    starlark_type,
    str_starlark,
    truth,
)

# ----------------------------------------------------------- type names


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "NoneType"),
        (True, "bool"),
        (False, "bool"),
        (0, "int"),
        (1.5, "float"),
        ("hi", "string"),
        ((1, 2), "tuple"),
    ],
)
def test_starlark_type(value, expected):
    assert starlark_type(value) == expected


def test_starlark_type_collections():
    m = Mutability()
    assert starlark_type(StarlarkList([1], m)) == "list"
    assert starlark_type(Dict({"k": 1}, m)) == "dict"
    assert starlark_type(StarlarkSet([1], m)) == "set"
    assert starlark_type(Range(0, 10, 1)) == "range"


# ----------------------------------------------------------- truth


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, False),
        (True, True),
        (False, False),
        (0, False),
        (1, True),
        (0.0, False),
        (1.5, True),
        ("", False),
        ("hi", True),
        ((), False),
        ((1,), True),
    ],
)
def test_truth(value, expected):
    assert truth(value) is expected


def test_truth_collections():
    m = Mutability()
    assert truth(StarlarkList([], m)) is False
    assert truth(StarlarkList([1], m)) is True
    assert truth(Dict({}, m)) is False
    assert truth(Dict({"k": 1}, m)) is True
    assert truth(Range(0, 0, 1)) is False
    assert truth(Range(0, 5, 1)) is True


# ----------------------------------------------------------- equality


def test_equal_same_type():
    assert equal(1, 1)
    assert not equal(1, 2)
    assert equal("a", "a")
    assert equal((1, 2), (1, 2))


def test_equal_int_float_cross():
    assert equal(1, 1.0)
    assert equal(2.5, 2.5)


def test_equal_bool_int_distinct():
    # Spec: True == 1 is False.
    assert not equal(True, 1)
    assert not equal(False, 0)


def test_equal_lists():
    m = Mutability()
    a = StarlarkList([1, 2, 3], m)
    b = StarlarkList([1, 2, 3], m)
    c = StarlarkList([1, 2], m)
    assert equal(a, b)
    assert not equal(a, c)


def test_equal_dicts_unordered():
    m = Mutability()
    a = Dict({"a": 1, "b": 2}, m)
    b = Dict({"b": 2, "a": 1}, m)
    assert equal(a, b)


# ----------------------------------------------------------- ordering


def test_less_than_int():
    assert less_than(1, 2)
    assert not less_than(2, 1)


def test_less_than_strings():
    assert less_than("a", "b")
    assert not less_than("b", "a")


def test_less_than_tuples_lex():
    assert less_than((1, 2), (1, 3))
    assert less_than((1, 2), (1, 2, 0))
    assert not less_than((1, 2), (1, 2))


def test_less_than_cross_type_errors():
    with pytest.raises(EvalError):
        less_than(1, "a")


# ----------------------------------------------------------- mutability


def test_mutability_freeze_blocks_writes():
    mod = Module("m")
    lst = StarlarkList([1, 2], mod.mutability)
    lst.append(3)
    assert list(lst) == [1, 2, 3]
    mod.freeze()
    with pytest.raises(EvalError):
        lst.append(4)


def test_module_freeze_propagates():
    mod = Module("m")
    a = StarlarkList([1], mod.mutability)
    b = Dict({"k": 1}, mod.mutability)
    mod.freeze()
    with pytest.raises(EvalError):
        a.append(2)
    with pytest.raises(EvalError):
        b["new"] = 2


def test_immutable_default():
    # No mutability arg -> immutable (universe).
    lst = StarlarkList([1, 2])
    with pytest.raises(EvalError):
        lst.append(3)


# ----------------------------------------------------------- list ops


def test_list_basic_ops():
    m = Mutability()
    lst = StarlarkList([1, 2], m)
    lst.append(3)
    lst.insert(0, 0)
    assert list(lst) == [0, 1, 2, 3]
    assert lst.pop() == 3
    lst.remove_value(1)
    assert list(lst) == [0, 2]


def test_list_index_of():
    m = Mutability()
    lst = StarlarkList(["a", "b", "c"], m)
    assert lst.index_of("b") == 1
    with pytest.raises(EvalError):
        lst.index_of("z")


# ----------------------------------------------------------- dict ops


def test_dict_basic_ops():
    m = Mutability()
    d = Dict({"a": 1}, m)
    d["b"] = 2
    assert len(d) == 2
    assert d["a"] == 1
    assert d.get("missing", -1) == -1
    assert d.keys() == ["a", "b"]


def test_dict_unhashable_key():
    m = Mutability()
    d = Dict(mutability=m)
    with pytest.raises(EvalError):
        d[StarlarkList([], m)] = 1


def test_dict_pop_missing():
    m = Mutability()
    d = Dict({"a": 1}, m)
    with pytest.raises(EvalError):
        d.pop("missing")
    assert d.pop("missing", "default") == "default"


# ----------------------------------------------------------- set ops


def test_set_basic_ops():
    m = Mutability()
    s = StarlarkSet([1, 2, 3], m)
    s.add(4)
    assert 4 in s
    s.discard(2)
    assert 2 not in s


def test_set_unhashable():
    m = Mutability()
    s = StarlarkSet(mutability=m)
    with pytest.raises(EvalError):
        s.add(StarlarkList([], m))


# ----------------------------------------------------------- range


def test_range_iter():
    assert list(Range(0, 5, 1)) == [0, 1, 2, 3, 4]
    assert list(Range(5, 0, -1)) == [5, 4, 3, 2, 1]
    assert list(Range(0, 10, 3)) == [0, 3, 6, 9]


def test_range_contains():
    r = Range(0, 10, 2)
    assert 4 in r
    assert 5 not in r
    assert 10 not in r


def test_range_zero_step():
    with pytest.raises(EvalError):
        Range(0, 5, 0)


def test_range_equal_empty():
    assert Range(0, 0, 1) == Range(5, 5, 1)


# ----------------------------------------------------------- repr


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "None"),
        (True, "True"),
        (False, "False"),
        (1, "1"),
        (-3, "-3"),
        ("hi", '"hi"'),
        ('he said "hi"', "'he said \"hi\"'"),
        ((1, 2), "(1, 2)"),
        ((1,), "(1,)"),
        ((), "()"),
    ],
)
def test_repr(value, expected):
    assert repr_starlark(value) == expected


def test_repr_collections():
    m = Mutability()
    assert repr_starlark(StarlarkList([1, 2, 3], m)) == "[1, 2, 3]"
    assert repr_starlark(Dict({"a": 1}, m)) == '{"a": 1}'


def test_str_string_unquoted():
    assert str_starlark("hello") == "hello"
    assert str_starlark(42) == "42"


# ----------------------------------------------------------- hashability


def test_hashable_basics():
    check_hashable(None)
    check_hashable(True)
    check_hashable(0)
    check_hashable(1.5)
    check_hashable("hi")
    check_hashable((1, "a"))


def test_unhashable_collections():
    m = Mutability()
    with pytest.raises(EvalError):
        check_hashable(StarlarkList([1], m))
    with pytest.raises(EvalError):
        check_hashable(Dict({"k": 1}, m))
