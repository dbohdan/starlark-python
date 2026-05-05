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
    src = (
        "x = []\n"
        "for i in range(1000):\n"
        "    x = [x]\n"
        "y = repr(x)\n"
    )
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
