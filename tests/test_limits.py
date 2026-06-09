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
        "y = x + x\n"  # 16M (exactly at cap)
        "z = y + y\n"  # 32M (over the cap)
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


# --------------------------------------------------------- integer magnitude


def test_squaring_loop_trips_with_clean_evalerror():
    # A doubling-of-bits squaring loop reaches a multi-gigabit int in a few
    # dozen cheap-looking steps. The pre-op bit-length cap must reject it as a
    # clean EvalError before the oversized multiply ever runs.
    src = "x = 3\nfor i in range(40):\n    x = x * x\n"
    with pytest.raises(EvalError, match="too large"):
        starlark.exec_file(src)


def test_shift_accumulation_trips():
    # Each shift count stays under the per-shift limit, but the accumulated
    # value crosses MAX_INT_BITS — the result-size check catches it.
    src = "x = 1\nfor i in range(2000):\n    x = x << 512\n"
    with pytest.raises(EvalError, match="too large"):
        starlark.exec_file(src)


def test_oversized_hex_literal_rejected():
    from starlark.eval.limits import MAX_INT_BITS

    # A hex literal isn't digit-capped by CPython, so it parses fine; the
    # literal-eval cap must reject one that exceeds MAX_INT_BITS.
    lit = "0x" + "f" * (MAX_INT_BITS // 4 + 16)
    with pytest.raises(EvalError, match="too large"):
        starlark.eval(lit)


def test_int_from_oversized_string_rejected():
    from starlark.eval.limits import MAX_INT_BITS

    digits = MAX_INT_BITS // 4 + 16  # hex digits -> 4 bits each, over the cap
    with pytest.raises(EvalError, match="too large"):
        starlark.eval(f"int('0x' + '{'f' * digits}', 16)")


def test_int_just_under_cap_succeeds():
    from starlark.eval.limits import MAX_INT_BITS

    # 1 << (MAX_INT_BITS - 1) is exactly MAX_INT_BITS bits — allowed.
    m = starlark.exec_file(f"x = 1\nfor i in range({(MAX_INT_BITS - 1) // 512}):\n    x = x << 512\n")
    assert m.globals["x"].bit_length() <= MAX_INT_BITS


def test_floordiv_mod_shift_on_cap_sized_int_do_not_trip():
    from starlark.eval.limits import MAX_INT_BITS

    # Build a near-cap int, then //, %, >> on it must not spuriously trip the
    # cap — none of those operations can grow the value.
    shifts = (MAX_INT_BITS - 2) // 512
    base = f"x = 1\nfor i in range({shifts}):\n    x = x << 512\n"
    m = starlark.exec_file(
        base + "a = x // 2\nb = x % 7\nc = x >> 1000\nd = -x\ne = x & 255\n"
    )
    assert m.globals["a"].bit_length() <= MAX_INT_BITS
    assert m.globals["c"].bit_length() <= MAX_INT_BITS
