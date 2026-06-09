"""Tests for the evaluator."""

from __future__ import annotations

import pytest

import starlark
from starlark.eval import Dict, EvalError, Module, StarlarkList


def run(source: str, **env) -> Module:
    return starlark.exec_file(source, predeclared=env)


def expr(source: str, **env):
    return starlark.eval(source, **env)


# ----------------------------------------------------------- arithmetic


def test_int_arith():
    assert expr("1 + 2") == 3
    assert expr("10 - 4") == 6
    assert expr("3 * 4") == 12
    assert expr("9 // 2") == 4
    assert expr("9 % 4") == 1
    # No `**` power operator in Starlark.


def test_float_arith():
    assert expr("1.5 + 2.5") == 4.0
    assert expr("7.0 / 2") == 3.5


def test_division_by_zero():
    with pytest.raises(EvalError):
        expr("1 / 0")
    with pytest.raises(EvalError):
        expr("1 // 0")


def test_arbitrary_precision():
    assert expr("99999999999999 * 99999999999999") == 99999999999999 * 99999999999999


def test_unary_ops():
    assert expr("-3") == -3
    assert expr("+3") == 3
    assert expr("~5") == -6
    assert expr("not True") is False
    assert expr("not 0") is True


def test_bitwise():
    assert expr("0b1010 & 0b1100") == 0b1000
    assert expr("0b1010 | 0b0001") == 0b1011
    assert expr("0b1010 ^ 0b1111") == 0b0101
    assert expr("1 << 8") == 256
    assert expr("256 >> 2") == 64


# ----------------------------------------------------------- comparisons


def test_comparisons():
    assert expr("1 == 1") is True
    assert expr("1 != 2") is True
    assert expr("1 < 2") is True
    assert expr("2 <= 2") is True
    assert expr("3 > 2") is True
    assert expr("3 >= 3") is True


def test_bool_int_distinct():
    # Spec: True == 1 is False.
    assert expr("True == 1") is False
    assert expr("False == 0") is False


def test_in_operator():
    assert expr("'a' in 'abc'") is True
    assert expr("1 in [1, 2, 3]") is True
    assert expr("'k' in {'k': 1}") is True
    assert expr("4 not in [1, 2, 3]") is True


# ----------------------------------------------------------- collections


def test_list_literal():
    v = expr("[1, 2, 3]")
    assert isinstance(v, StarlarkList)
    assert list(v) == [1, 2, 3]


def test_tuple_literal():
    assert expr("(1, 2, 3)") == (1, 2, 3)
    assert expr("()") == ()
    assert expr("(1,)") == (1,)


def test_dict_literal():
    v = expr("{'a': 1, 'b': 2}")
    assert isinstance(v, Dict)
    assert v["a"] == 1
    assert v["b"] == 2


def test_indexing():
    assert expr("[1, 2, 3][1]") == 2
    assert expr("'hello'[0]") == "h"
    assert expr("'hello'[-1]") == "o"
    assert expr("{'a': 1}['a']") == 1


def test_slicing():
    assert expr("[1, 2, 3, 4, 5][1:4]") == [1, 2, 3, 4, 5][1:4] or list(
        expr("[1, 2, 3, 4, 5][1:4]")
    ) == [2, 3, 4]
    assert expr("'hello'[1:4]") == "ell"
    assert expr("'hello'[::-1]") == "olleh"


def test_string_concat():
    assert expr("'a' + 'b' + 'c'") == "abc"


def test_list_concat():
    v = expr("[1, 2] + [3, 4]")
    assert list(v) == [1, 2, 3, 4]


def test_string_multiply():
    assert expr("'ab' * 3") == "ababab"


# ----------------------------------------------------------- statements


def test_simple_program():
    m = run("x = 1 + 2\ny = x * 2\n")
    assert m.globals["x"] == 3
    assert m.globals["y"] == 6


def test_augmented_assignment():
    m = run("x = 1\nx += 5\nx *= 2\n")
    assert m.globals["x"] == 12


def test_list_aug_assign_in_place():
    m = run("a = [1, 2]\nb = a\na += [3]\n")
    # Augmented += on lists mutates in place.
    assert list(m.globals["a"]) == [1, 2, 3]
    assert list(m.globals["b"]) == [1, 2, 3]


def test_if_else():
    m = run(
        "x = 5\n"
        "if x > 0:\n"
        "    sign = 'pos'\n"
        "elif x < 0:\n"
        "    sign = 'neg'\n"
        "else:\n"
        "    sign = 'zero'\n"
    )
    assert m.globals["sign"] == "pos"


def test_for_loop():
    m = run("total = 0\nfor i in [1, 2, 3, 4]:\n    total += i\n")
    assert m.globals["total"] == 10


def test_for_break():
    m = run("for i in [1, 2, 3]:\n    if i == 2:\n        break\n    last = i\n")
    assert m.globals["last"] == 1


def test_for_continue():
    m = run(
        "vals = []\n"
        "for i in [1, 2, 3, 4]:\n"
        "    if i % 2 == 0:\n"
        "        continue\n"
        "    vals = vals + [i]\n"
    )
    assert list(m.globals["vals"]) == [1, 3]


def test_tuple_unpack():
    m = run("a, b = 1, 2\nc, d = (3, 4)\n")
    assert m.globals["a"] == 1
    assert m.globals["b"] == 2
    assert m.globals["c"] == 3
    assert m.globals["d"] == 4


# ----------------------------------------------------------- functions


def test_def_and_call():
    m = run("def add(a, b):\n    return a + b\nz = add(3, 4)\n")
    assert m.globals["z"] == 7


def test_def_default_arg():
    m = run("def f(x, y=10):\n    return x + y\na = f(1)\nb = f(1, 2)\n")
    assert m.globals["a"] == 11
    assert m.globals["b"] == 3


def test_def_kwargs():
    m = run("def f(a, b):\n    return a - b\nz = f(b=1, a=10)\n")
    assert m.globals["z"] == 9


def test_def_varargs():
    m = run("def f(*args):\n    return args\nz = f(1, 2, 3)\n")
    assert m.globals["z"] == (1, 2, 3)


def test_def_kwargs_dict():
    m = run("def f(**kw):\n    return kw\nz = f(a=1, b=2)\n")
    z = m.globals["z"]
    assert isinstance(z, Dict)
    assert z["a"] == 1
    assert z["b"] == 2


def test_lambda():
    m = run("sq = lambda x: x*x\nz = sq(5)\n")
    assert m.globals["z"] == 25


def test_closure():
    m = run(
        "def make_counter(n):\n"
        "    def counter():\n"
        "        return n\n"
        "    return counter\n"
        "c = make_counter(42)\n"
        "v = c()\n"
    )
    assert m.globals["v"] == 42


def test_recursion_forbidden():
    # Per the Starlark spec, recursion is not allowed.
    with pytest.raises(EvalError, match="called recursively"):
        run("def fact(n):\n    if n <= 1: return 1\n    return n * fact(n - 1)\nz = fact(5)\n")


# ----------------------------------------------------------- comprehensions


def test_list_comprehension():
    v = expr("[x*2 for x in [1, 2, 3]]")
    assert list(v) == [2, 4, 6]


def test_list_comprehension_with_if():
    v = expr("[x for x in [1, 2, 3, 4] if x % 2 == 0]")
    assert list(v) == [2, 4]


def test_nested_comprehension():
    v = expr("[(a, b) for a in [1, 2] for b in [3, 4]]")
    assert list(v) == [(1, 3), (1, 4), (2, 3), (2, 4)]


def test_dict_comprehension():
    v = expr("{x: x*x for x in [1, 2, 3]}")
    assert isinstance(v, Dict)
    assert v[1] == 1
    assert v[2] == 4
    assert v[3] == 9


# ----------------------------------------------------------- control flow signals


def test_unbound_local():
    with pytest.raises(EvalError):
        run("def f():\n    return x\nf()\n")


def test_string_format_percent():
    assert expr("'x=%d, y=%s' % (3, 'hi')") == "x=3, y=hi"
    assert expr("'%s' % None") == "None"
    assert expr("'%r' % 'hi'") == '"hi"'


# ----------------------------------------------------------- builtin dispatch safety net


def test_builtin_nonevalerror_normalized_to_evalerror():
    # A builtin that raises a non-EvalError, non-TypeError Python exception
    # would otherwise escape raw and break the host contract `except EvalError`.
    # The dispatch catch-all must normalize it.
    from starlark.eval import BuiltinFunction

    def boom():
        raise ValueError("kaboom")

    fn = BuiltinFunction(name="boom", impl=boom)
    with pytest.raises(EvalError, match="kaboom"):
        run("boom()\n", boom=fn)


def test_builtin_resource_limit_not_masked():
    # Limit exceptions subclass EvalError; the EvalError arm must let them
    # through unchanged rather than the catch-all re-wrapping them.
    from starlark.eval import BuiltinFunction
    from starlark.eval.errors import StepLimitExceeded

    def over_limit():
        raise StepLimitExceeded("step limit exceeded")

    fn = BuiltinFunction(name="over_limit", impl=over_limit)
    with pytest.raises(StepLimitExceeded):
        run("over_limit()\n", over_limit=fn)


def test_internal_typeerror_not_mislabeled_as_arg_error():
    # A TypeError raised *inside* a builtin (not at the call boundary) must
    # not be string-munged into an argument-binding message. It should reach
    # the host as a normalized EvalError carrying the original text.
    from starlark.eval import BuiltinFunction

    def internal_fault():
        return None + 1  # raises TypeError inside the body

    fn = BuiltinFunction(name="internal_fault", impl=internal_fault)
    with pytest.raises(EvalError, match="TypeError") as exc:
        run("internal_fault()\n", internal_fault=fn)
    # The arg-binding rewrite strips an "() " prefix and quotes; a genuine
    # internal fault keeps its message intact.
    assert "unsupported operand" in exc.value.message


def test_arg_binding_typeerror_still_rewritten():
    # A real arity mismatch still gets the cleaned-up, Java-style message.
    from starlark.eval import BuiltinFunction

    def takes_none():
        return 1

    fn = BuiltinFunction(name="takes_none", impl=takes_none)
    with pytest.raises(EvalError) as exc:
        run("takes_none(1, 2, 3)\n", takes_none=fn)
    assert "takes_none()" not in exc.value.message
    assert "TypeError" not in exc.value.message


def test_arg_binding_detection_robust_through_partial_wrapper():
    # Method receivers are bound with functools.partial; classification must
    # work through that wrapper. An internal TypeError (right arity, faulty
    # body) must not be mislabeled, and a real arity mismatch must be.
    import functools

    from starlark.eval import BuiltinFunction

    def method(receiver, key):
        return None + 1  # internal TypeError when called with correct arity

    fn = BuiltinFunction(name="m", impl=functools.partial(method, "recv"))

    with pytest.raises(EvalError, match="unsupported operand"):
        run("m('k')\n", m=fn)  # correct arity -> internal fault, kept faithful

    with pytest.raises(EvalError) as exc:
        run("m('k', 'extra')\n", m=fn)  # wrong arity -> arg-binding error
    assert "unsupported operand" not in exc.value.message
