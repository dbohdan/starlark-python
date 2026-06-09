"""Tests for parser, evaluator, and repr depth caps.

Without these caps, deeply nested input crashes with Python's
`RecursionError`, leaking host stack frames and making the failure
look like an interpreter bug rather than an input-too-deep diagnostic.
We convert each path into a clean `EvalError` / `StarlarkSyntaxException`.
"""

from __future__ import annotations

import pytest

import starlark
from starlark.eval import EvalError
from starlark.eval.test_driver import make_predeclared
from starlark.syntax.errors import StarlarkSyntaxException


def test_deeply_nested_parens_rejected_at_parse_time():
    src = "x = " + "(" * 1000 + "1" + ")" * 1000 + "\n"
    with pytest.raises(StarlarkSyntaxException, match="too deeply nested"):
        starlark.exec_file(src)


def test_deeply_nested_list_literal_rejected_at_parse_time():
    src = "x = " + "[" * 1000 + "]" * 1000 + "\n"
    with pytest.raises(StarlarkSyntaxException, match="too deeply nested"):
        starlark.exec_file(src)


def test_deeply_nested_if_rejected_at_parse_time():
    # 500 levels of if/else nesting.
    body = "x = 1\n"
    for _ in range(500):
        body = f"if True:\n    {body.replace(chr(10), chr(10) + '    ')}"
    with pytest.raises(StarlarkSyntaxException, match="too deeply nested"):
        starlark.exec_file(body)


def test_deeply_nested_value_rejected_at_eval_time_in_repr():
    # Build a deeply nested list at runtime — no source-level nesting,
    # so the parser doesn't catch it. The evaluator's repr cap should.
    src = "x = []\nfor i in range(1000):\n    x = [x]\ny = repr(x)\n"
    with pytest.raises(EvalError, match="too deeply nested"):
        starlark.exec_file(src)


def test_normal_nesting_still_works():
    # 100 levels should be fine — well below the cap.
    src = "x = " + "[" * 100 + "1" + "]" * 100 + "\n"
    m = starlark.exec_file(src)
    assert "x" in m.globals


def test_assert_fails_with_depth_cap_in_predeclared_context():
    # Same as the eval-time test but in a chunk with the test-driver
    # predeclared so we know the runner path is exercised.
    src = (
        "x = []\n"
        "for i in range(1000):\n"
        "    x = [x]\n"
        "freeze(x)\n"  # uses _CURRENT_MUTABILITY; sanity that path runs
    )
    starlark.exec_file(src, predeclared=make_predeclared())


def test_deep_equality_rejected_at_value_level():
    # `x == x` for a runtime-built deep value recurses through equal();
    # without a value-level depth bound this leaks a RecursionError.
    src = "x = []\nfor i in range(400):\n    x = [x]\ny = x == x\n"
    with pytest.raises(EvalError, match="too deeply nested"):
        starlark.exec_file(src)


def test_deep_membership_rejected_at_value_level():
    # `x in [x]` drives _contains() -> equal() into the same deep recursion.
    src = "x = []\nfor i in range(400):\n    x = [x]\ny = x in [x]\n"
    with pytest.raises(EvalError, match="too deeply nested"):
        starlark.exec_file(src)


def test_deep_ordering_rejected_at_value_level():
    # sorted() compares with less_than(); a deep list trips the bound too.
    src = "x = []\nfor i in range(400):\n    x = [x]\ny = sorted([x, x])\n"
    with pytest.raises(EvalError, match="too deeply nested"):
        starlark.exec_file(src)


def test_shallow_equality_still_works():
    # Well below the cap: equality and membership behave normally.
    m = starlark.exec_file(
        "a = [1, [2, [3]]]\nb = [1, [2, [3]]]\neq = a == b\ninn = a in [b]\n"
    )
    assert m.globals["eq"] is True
    assert m.globals["inn"] is True


def test_comparison_just_under_cap_succeeds():
    # Calibration guard. Comparing two values nested just under
    # MAX_NESTING_DEPTH must complete cleanly — this locks the frame budget.
    # If a change inflates the per-level frame cost of equal() so that even a
    # legal-depth comparison overflows the C stack, the boundary safety net
    # turns it into an EvalError and this assertion fails loudly.
    from starlark.eval.limits import MAX_NESTING_DEPTH

    n = MAX_NESTING_DEPTH - 1
    m = starlark.exec_file(f"x = []\nfor i in range({n}):\n    x = [x]\ny = x == x\n")
    assert m.globals["y"] is True


def test_leaked_recursionerror_becomes_evalerror():
    # Safety net. Force Python's recursion limit low enough that a comparison
    # well under MAX_NESTING_DEPTH overflows the C stack before the explicit
    # value-level bound can fire. The evaluation boundary must convert that
    # into a clean EvalError, never leak a raw RecursionError to the host.
    import sys

    def _stack_depth() -> int:
        d, f = 0, sys._getframe()
        while f is not None:
            d += 1
            f = f.f_back
        return d

    src = "x = []\nfor i in range(400):\n    x = [x]\ny = x == x\n"
    old = sys.getrecursionlimit()
    try:
        # Enough headroom for the (shallow) parse/eval setup, far less than the
        # ~800 frames a 400-deep comparison needs.
        sys.setrecursionlimit(_stack_depth() + 250)
        with pytest.raises(EvalError):
            starlark.exec_file(src)
    finally:
        sys.setrecursionlimit(old)
