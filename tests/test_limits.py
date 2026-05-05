"""Tests for the centralized container-size limit.

Adversarial inputs that would otherwise materialize 10^9-element
containers should now raise a clean `EvalError` instead of OOM-ing the
host. We test the most common allocation paths: `list(range(big))`,
`tuple(range(big))`, `[x] + huge`, `s * N`, `set(range(big))`,
`sorted(range(big))`, `list.extend(range(big))`.
"""

from __future__ import annotations

import pytest

import starlark
from starlark.eval import EvalError


def test_list_of_huge_range_rejected():
    with pytest.raises(EvalError, match="excessive capacity"):
        starlark.eval("list(range(1099511627776))")


def test_tuple_of_huge_range_rejected():
    with pytest.raises(EvalError, match="excessive capacity"):
        starlark.eval("tuple(range(1099511627776))")


def test_set_of_huge_range_rejected():
    with pytest.raises(EvalError, match="excessive capacity"):
        starlark.eval("set(range(1099511627776))")


def test_sorted_of_huge_range_rejected():
    with pytest.raises(EvalError, match="excessive capacity"):
        starlark.eval("sorted(range(1099511627776))")


def test_reversed_of_huge_range_rejected():
    with pytest.raises(EvalError, match="excessive capacity"):
        starlark.eval("reversed(range(1099511627776))")


def test_enumerate_of_huge_range_rejected():
    with pytest.raises(EvalError, match="excessive capacity"):
        starlark.eval("enumerate(range(1099511627776))")


def test_list_repeat_rejected():
    # Repeat reports a different message ("excessive repeat" or "signed
    # 32-bit range") to match the Java reference's wording.
    with pytest.raises(EvalError, match=r"excessive repeat|signed 32-bit"):
        starlark.eval("[1, 2, 3] * 1000000000000")


def test_string_repeat_rejected():
    with pytest.raises(EvalError, match=r"excessive repeat|signed 32-bit"):
        starlark.eval('"ab" * 1000000000000')


def test_list_concat_rejected():
    src = (
        "x = [0] * (1 << 23)\n"  # 8M elements (under the cap)
        "y = x + x\n"             # 16M (exactly at cap)
        "z = y + y\n"             # 32M (over the cap)
    )
    with pytest.raises(EvalError, match="excessive capacity"):
        starlark.exec_file(src)


def test_extend_with_huge_range_rejected():
    with pytest.raises(EvalError, match="excessive capacity"):
        starlark.exec_file("a = []\na.extend(range(1099511627776))\n")


def test_normal_sized_operations_still_work():
    # 1M elements should still work fine — well under the cap.
    starlark.eval("list(range(1000000))")
    starlark.eval("tuple(range(1000000))")
    starlark.eval("[0] * 1000000")
