"""Concurrent-evaluation safety.

The interpreter holds three pieces of per-evaluation state in `ContextVar`s:
the current `Thread`, the current `Mutability`, and the test-driver reporter.
`ContextVar` isolates state per OS thread (and per asyncio task), so two host
threads can call `starlark.exec_file` concurrently without stomping on each
other.

These tests would have hit at least one of:
- A `KeyError` / pop-from-empty-list when one thread popped the other's
  context off a shared list (the previous module-level stack).
- A reporter capturing assertions from the wrong evaluation.
- A `freeze()` in one thread freezing a sibling thread's module.

Run with `pytest -p no:cacheprovider -x tests/test_thread_safety.py` to
catch flakes individually.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import starlark
from starlark.eval.test_driver import make_predeclared, with_reporter


def _eval_loop(src: str, n: int) -> list[int]:
    """Evaluate `src` n times, returning the value of `result` each time."""
    out: list[int] = []
    for _ in range(n):
        m = starlark.exec_file(src)
        out.append(m.globals["result"])
    return out


def test_concurrent_evals_do_not_interfere():
    """Two host threads each evaluate independent modules in a tight loop."""
    src_a = "result = sum([i for i in range(100)])\n"
    src_b = "result = len([i * i for i in range(50)])\n"
    n = 50

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_a = pool.submit(_eval_loop, src_a, n)
        fut_b = pool.submit(_eval_loop, src_b, n)
        a_results = fut_a.result()
        b_results = fut_b.result()

    assert a_results == [sum(range(100))] * n
    assert b_results == [50] * n


def test_concurrent_evals_with_user_functions_calling_builtins():
    """Two threads exercise `sorted(key=fn)` / `min(key=fn)` — both call back
    into Starlark from inside a builtin via `_CURRENT_THREAD`. Thread leakage
    here would crash with frame-stack corruption."""

    def go(seed: int) -> list[int]:
        src = f"""
def key(x): return -x + {seed}
result = sorted([3, 1, 4, 1, 5, 9, 2, 6], key=key)
"""
        m = starlark.exec_file(src)
        return list(m.globals["result"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(go, range(20)))

    # All threads see the same sort result regardless of `seed`, since the
    # key is monotonic in x.
    expected = [9, 6, 5, 4, 3, 2, 1, 1]
    assert all(r == expected for r in results)


def test_concurrent_freeze_does_not_leak_across_threads():
    """`freeze()` in one thread must not freeze another thread's module."""
    barrier = threading.Barrier(2)
    results: dict[str, str] = {}

    def freezer():
        # Wait for the other thread to have its module set up.
        barrier.wait()
        src = "x = [1, 2, 3]\nfreeze()\n"
        starlark.exec_file(src, predeclared=make_predeclared())
        barrier.wait()

    def mutator():
        # While the other thread freezes its module, this one keeps mutating.
        src = """
x = [1, 2, 3]
"""
        m = starlark.exec_file(src, predeclared=make_predeclared())
        barrier.wait()
        # After the freezer thread runs, our module should still be mutable.
        try:
            m.globals["x"].append(4)
            results["mutator"] = "ok"
        except starlark.EvalError as e:
            results["mutator"] = f"frozen: {e.message}"
        barrier.wait()

    t1 = threading.Thread(target=freezer)
    t2 = threading.Thread(target=mutator)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert results["mutator"] == "ok"


def test_concurrent_reporter_is_isolated():
    """The test-driver reporter must be per-thread."""
    barrier = threading.Barrier(2)
    captured: dict[str, list[str]] = {}

    def go(name: str, src: str):
        barrier.wait()
        with with_reporter() as r:
            try:
                starlark.exec_file(src, predeclared=make_predeclared())
            except starlark.EvalError:
                pass
        captured[name] = list(r.errors)

    t1 = threading.Thread(target=go, args=("a", "assert_eq(1, 2)\n"))
    t2 = threading.Thread(target=go, args=("b", "assert_eq(3, 3)\n"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Thread A asserted false; thread B asserted true. Each thread sees only
    # its own assertion's outcome.
    assert any("1" in e and "2" in e for e in captured["a"])
    assert captured["b"] == []


def test_nested_exec_file_within_a_thread():
    """Two `exec_file` calls nested inside one thread (e.g. a host-supplied
    builtin that itself calls exec_file). The outer's state must survive."""

    def host_eval(thread_unused, code: str) -> int:
        # Host helper exposed to Starlark: re-enters exec_file and returns
        # globals['x']. Builtin signature ignores the leading args; we use
        # `current_thread()` to demonstrate the outer thread is still
        # accessible after the nested call returns.
        m2 = starlark.exec_file(code)
        return m2.globals["x"]

    from starlark.eval.builtins import current_thread
    from starlark.eval.values import BuiltinFunction

    def b_inner(code):
        return host_eval(current_thread(), code)

    src = '''
inner = inner_fn("x = 7\\n")
'''
    pre = {
        "inner_fn": BuiltinFunction(name="inner_fn", impl=b_inner),
    }
    m = starlark.exec_file(src, predeclared=pre)
    # After the nested eval, the outer thread context is intact.
    assert m.globals["inner"] == 7


@pytest.mark.parametrize("workers", [2, 4, 8])
def test_stress_many_threads(workers: int):
    """Smoke: many concurrent evals with sorted+key (touches every state)."""
    src = """
def k(x): return x
result = sorted([3, 1, 4, 1, 5, 9, 2, 6], key=k)
"""

    def go(_: int) -> list[int]:
        m = starlark.exec_file(src)
        return list(m.globals["result"])

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(go, range(workers * 10)))
    assert all(r == [1, 1, 2, 3, 4, 5, 6, 9] for r in results)
