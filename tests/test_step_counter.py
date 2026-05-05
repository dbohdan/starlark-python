"""Step counter (CPU-time bound).

The interpreter charges one step at three sites: every statement executed,
every expression node visited, and every function call (`call()`). The
unit is intentionally coarse and matches starlark-java's documented
choice — see `security/threat-model.md`.

These tests cover:
- The default (unlimited) preserves behavior.
- Setting `max_steps` raises `StepLimitExceeded` when exceeded.
- The `on_max_steps` callback fires once before the raise.
- The error class hierarchy is `StepLimitExceeded < ResourceLimitExceeded < EvalError`.
- Adversarial patterns from the threat model abort cleanly:
  `for i in range(N)` and `[x for x in range(N)]` for large N.
"""

from __future__ import annotations

import pytest

import starlark
from starlark import (
    EvalError,
    ResourceLimitExceeded,
    StepLimitExceeded,
    Thread,
)


def test_unlimited_default_preserves_behavior():
    m = starlark.exec_file("x = sum([i for i in range(100)])\n")
    assert m.globals["x"] == sum(range(100))


def test_step_count_is_recorded():
    """Without a cap, `steps` is still incremented; hosts can read it."""
    src = "x = 1 + 2 + 3\n"
    # We need to drive a Thread directly to read `steps` after.
    from starlark.eval.builtins import (
        make_universal,
        with_mutability,
        with_thread,
    )
    from starlark.eval.evaluator import eval_file
    from starlark.eval.module import Module
    from starlark.syntax import Lexer, parse, resolve

    file = parse(src)
    locs = Lexer(src).locs
    uni = make_universal()
    resolve(file, locs, universal=frozenset(uni))
    module = Module("<test>")
    thread = Thread(module=module, universal=uni, locs=locs)
    with with_mutability(module.mutability), with_thread(thread):
        eval_file(file, thread)
    # `1 + 2 + 3` parses as a left-associative tree with 5 expression
    # nodes (3 ints + 2 binops); the assignment statement adds 1; expressions
    # tick recursively. We don't assert an exact count — just that it's > 0.
    assert thread.steps > 0


def test_max_steps_raises_step_limit_exceeded():
    src = """
total = 0
for i in range(1000):
    total = total + i
"""
    with pytest.raises(StepLimitExceeded) as exc_info:
        starlark.exec_file(src, max_steps=100)
    assert "too many steps" in exc_info.value.message
    assert "> 100" in exc_info.value.message


def test_step_limit_exceeded_is_resource_limit_subclass():
    """Hosts should be able to catch as ResourceLimitExceeded or as EvalError."""
    src = "for i in range(10000): pass\n"
    with pytest.raises(ResourceLimitExceeded):
        starlark.exec_file(src, max_steps=50)
    with pytest.raises(EvalError):
        starlark.exec_file(src, max_steps=50)
    # And StepLimitExceeded itself:
    with pytest.raises(StepLimitExceeded):
        starlark.exec_file(src, max_steps=50)


def test_on_max_steps_callback_fires_once_before_raise():
    """Callback is invoked once; subsequent ticks raise without re-firing."""
    captured: list[int] = []

    def cb(thread: Thread) -> None:
        captured.append(thread.steps)

    src = "for i in range(10000): pass\n"
    with pytest.raises(StepLimitExceeded):
        starlark.exec_file(src, max_steps=100, on_max_steps=cb)
    assert len(captured) == 1
    assert captured[0] > 100


def test_on_max_steps_callback_can_raise_custom_error():
    """A callback that raises pre-empts the default StepLimitExceeded."""

    class MyDeadline(Exception):
        pass

    def cb(thread: Thread) -> None:
        raise MyDeadline(f"deadline at {thread.steps} steps")

    src = "for i in range(10000): pass\n"
    with pytest.raises(MyDeadline, match="deadline at"):
        starlark.exec_file(src, max_steps=100, on_max_steps=cb)


def test_step_count_bounds_huge_range_iteration():
    """The threat-model adversarial pattern: a tight loop over a huge range.

    Without a step cap this would run for a long time; with one it aborts
    after ~`max_steps` iterations.
    """
    src = "for i in range(1000000000): pass\n"
    with pytest.raises(StepLimitExceeded):
        starlark.exec_file(src, max_steps=10_000)


def test_step_count_bounds_comprehension():
    """A list comprehension with a hostile iterator."""
    src = "x = [i * 2 for i in range(1000000000)]\n"
    with pytest.raises(StepLimitExceeded):
        starlark.exec_file(src, max_steps=10_000)


def test_step_count_bounds_user_function_recursion_via_callback():
    """`sorted(key=fn)` calls fn() per element. Each callback ticks via call()."""
    src = """
def k(x): return -x
result = sorted([i for i in range(1000000)], key=k)
"""
    with pytest.raises(StepLimitExceeded):
        starlark.exec_file(src, max_steps=10_000)


def test_finite_program_completes_under_generous_cap():
    """A reasonable program runs to completion below a generous cap."""
    src = """
def square(n): return n * n
result = [square(i) for i in range(100)]
total = sum(result)
"""
    m = starlark.exec_file(src, max_steps=100_000)
    assert m.globals["total"] == sum(i * i for i in range(100))


def test_step_count_visible_after_run():
    """Hosts can inspect `Thread.steps` after a successful run."""
    from starlark.eval.builtins import (
        make_universal,
        with_mutability,
        with_thread,
    )
    from starlark.eval.evaluator import eval_file
    from starlark.eval.module import Module
    from starlark.syntax import Lexer, parse, resolve

    src = "x = sum([i for i in range(50)])\n"
    file = parse(src)
    locs = Lexer(src).locs
    uni = make_universal()
    resolve(file, locs, universal=frozenset(uni))
    module = Module("<test>")
    thread = Thread(module=module, universal=uni, locs=locs)
    with with_mutability(module.mutability), with_thread(thread):
        eval_file(file, thread)
    # 50 iterations + comprehension overhead + sum() + assignment.
    # Ballpark: a few hundred steps. Keep the assertion loose.
    assert 50 < thread.steps < 10_000
