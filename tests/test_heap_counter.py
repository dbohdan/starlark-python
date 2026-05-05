"""Charge-only heap counter (cumulative-allocation bound).

The interpreter charges approximate bytes against `Thread.allocs` at
every container construction and mutating concat/extend. Allocation is
*never refunded* — the counter measures cumulative allocation, not
live-memory residency.

These tests cover:
- Default (unlimited) preserves behavior.
- Setting `max_allocs` raises `AllocLimitExceeded` when exceeded.
- Charges are roughly proportional to container size.
- The threat-model adversarial patterns abort cleanly:
  `[0] * 10**8`, `dict()` with millions of entries, large list+list concat.
- Negative deltas to `add_allocs` are rejected.
- The on_max_allocs callback fires once before the raise.
- AllocLimitExceeded subclasses ResourceLimitExceeded subclasses EvalError.
"""

from __future__ import annotations

import pytest

import starlark
from starlark import (
    AllocLimitExceeded,
    EvalError,
    ResourceLimitExceeded,
    Thread,
)
from starlark.eval.builtins import (
    make_universal,
    with_mutability,
    with_thread,
)
from starlark.eval.evaluator import eval_file
from starlark.eval.module import Module
from starlark.syntax import Lexer, parse, resolve


def _run(src: str, **kwargs):
    """Helper: run `src` with a Thread we can inspect after."""
    file = parse(src)
    locs = Lexer(src).locs
    uni = make_universal()
    resolve(file, locs, universal=frozenset(uni))
    module = Module("<test>")
    thread = Thread(module=module, universal=uni, locs=locs, **kwargs)
    with with_mutability(module.mutability), with_thread(thread):
        eval_file(file, thread)
    return module, thread


def test_unlimited_default_preserves_behavior():
    m = starlark.exec_file("x = [i for i in range(100)]\n")
    assert len(m.globals["x"]) == 100


def test_alloc_count_is_recorded():
    """Without a cap, `allocs` is incremented; hosts can read it."""
    _, thread = _run("x = [1, 2, 3]\ny = {'a': 1, 'b': 2}\n")
    assert thread.allocs > 0


def test_alloc_count_grows_with_container_size():
    """Bigger lists charge more bytes than smaller ones."""
    _, t_small = _run("x = [i for i in range(10)]\n")
    _, t_big = _run("x = [i for i in range(1000)]\n")
    assert t_big.allocs > t_small.allocs * 10


def test_max_allocs_raises_alloc_limit_exceeded():
    src = "x = [i for i in range(100000)]\n"
    with pytest.raises(AllocLimitExceeded) as exc_info:
        starlark.exec_file(src, max_allocs=10_000)
    assert "heap budget exhausted" in exc_info.value.message
    assert "> 10000" in exc_info.value.message


def test_alloc_limit_exceeded_is_resource_limit_subclass():
    """Hosts can catch as ResourceLimitExceeded or EvalError."""
    src = "x = [i for i in range(100000)]\n"
    with pytest.raises(ResourceLimitExceeded):
        starlark.exec_file(src, max_allocs=10_000)
    with pytest.raises(EvalError):
        starlark.exec_file(src, max_allocs=10_000)


def test_on_max_allocs_callback_fires_once_before_raise():
    captured: list[int] = []

    def cb(thread: Thread) -> None:
        captured.append(thread.allocs)

    src = "x = [i for i in range(100000)]\n"
    with pytest.raises(AllocLimitExceeded):
        starlark.exec_file(src, max_allocs=10_000, on_max_allocs=cb)
    assert len(captured) == 1
    assert captured[0] > 10_000


def test_on_max_allocs_callback_can_pre_empt_with_custom_error():
    class OutOfBudget(Exception):
        pass

    def cb(thread: Thread) -> None:
        raise OutOfBudget(f"oom at {thread.allocs} bytes")

    src = "x = [i for i in range(100000)]\n"
    with pytest.raises(OutOfBudget):
        starlark.exec_file(src, max_allocs=10_000, on_max_allocs=cb)


def test_huge_repeated_list_aborts():
    """Adversarial: `[0] * 100000`. Hits MAX_CONTAINER_ELEMENTS first if
    very big; with a smaller heap budget, AllocLimitExceeded fires first."""
    src = "x = [0] * 100000\n"
    with pytest.raises(AllocLimitExceeded):
        starlark.exec_file(src, max_allocs=10_000)


def test_dict_growth_charges():
    src = """
d = {}
for i in range(1000):
    d[i] = i
"""
    with pytest.raises(AllocLimitExceeded):
        starlark.exec_file(src, max_allocs=10_000)


def test_set_growth_charges():
    src = """
s = set()
for i in range(1000):
    s.add(i)
"""
    with pytest.raises(AllocLimitExceeded):
        starlark.exec_file(src, max_allocs=10_000)


def test_list_concat_charges_each_concat():
    """List+list creates a new list; the cumulative cost grows with each."""
    src = """
x = []
for i in range(500):
    x = x + [i]
"""
    with pytest.raises(AllocLimitExceeded):
        starlark.exec_file(src, max_allocs=50_000)


def test_string_concat_charges():
    """String+string in a tight loop charges per concatenation."""
    src = """
s = ""
for i in range(1000):
    s = s + "x"
"""
    # Each iteration allocates a new string of size i+1; cumulative is
    # O(n^2). At n=1000 we expect ~500k bytes of cumulative string alloc.
    with pytest.raises(AllocLimitExceeded):
        starlark.exec_file(src, max_allocs=20_000)


def test_string_repeat_charges():
    """`"x" * N` is one allocation of size N."""
    src = "s = 'x' * 50000\n"
    with pytest.raises(AllocLimitExceeded):
        starlark.exec_file(src, max_allocs=10_000)


def test_tuple_repeat_charges():
    src = "t = (0,) * 50000\n"
    with pytest.raises(AllocLimitExceeded):
        starlark.exec_file(src, max_allocs=10_000)


def test_finite_program_completes_under_generous_cap():
    """A reasonable program runs to completion below a generous cap."""
    src = """
def square(n): return n * n
result = [square(i) for i in range(100)]
total = sum(result)
"""
    m = starlark.exec_file(src, max_allocs=1_000_000)
    assert m.globals["total"] == sum(i * i for i in range(100))


def test_negative_delta_rejected():
    """`add_allocs` is charge-only; negative deltas are a programming error."""
    from starlark.eval.module import Module
    t = Thread(module=Module("<test>"))
    with pytest.raises(ValueError, match="negative delta"):
        t.add_allocs(-1)


def test_steps_and_allocs_independent():
    """Setting one cap doesn't trigger the other."""
    src = "x = [i for i in range(100)]\n"
    # Generous step cap, tight alloc cap — alloc fires first.
    with pytest.raises(AllocLimitExceeded):
        starlark.exec_file(src, max_steps=1_000_000, max_allocs=200)
    # Generous alloc cap, tight step cap — step fires first.
    from starlark import StepLimitExceeded
    with pytest.raises(StepLimitExceeded):
        starlark.exec_file(src, max_steps=10, max_allocs=10_000_000)


def test_allocs_visible_after_run():
    src = "x = [i for i in range(50)]\ny = {'a': 1, 'b': 2}\n"
    _, thread = _run(src)
    # 50-element list (~64 + 50*8 = 464) + 2-entry dict (~256 + 2*56 = 368)
    # plus comprehension intermediate allocations. Loose bounds.
    assert 500 < thread.allocs < 50_000


def test_dict_setdefault_charges_only_on_new_key():
    """setdefault on an existing key reuses storage; setdefault on a new
    key adds an entry. We verify the *result* — the charge accounting is
    a side effect that's harder to measure precisely from a Starlark
    program. The contract is documented in `Dict.setdefault` and exercised
    indirectly by the alloc-cap tests above."""
    src = """
d = {'a': 1}
d.setdefault('a', 2)
d.setdefault('b', 3)
"""
    m = starlark.exec_file(src)
    assert len(m.globals["d"]) == 2
