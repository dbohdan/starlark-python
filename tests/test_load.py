"""Tests for the load() statement (Phase 11)."""

from __future__ import annotations

import pytest

import starlark
from starlark.eval import EvalError, Module


def test_load_no_loader_raises():
    src = 'load("m.star", "x")\n'
    with pytest.raises(EvalError, match="load.* not allowed"):
        starlark.exec_file(src)


def test_load_with_inline_loader():
    # Build the loaded module manually.
    loaded = Module("m.star")
    loaded.globals["foo"] = 42
    loaded.globals["bar"] = "hello"
    loaded.freeze()

    def loader(name: str) -> Module:
        assert name == "m.star"
        return loaded

    src = 'load("m.star", "foo", b = "bar")\nz = foo + 1\n'
    m = starlark.exec_file(src, loader=loader)
    assert m.globals["foo"] == 42
    assert m.globals["b"] == "hello"
    assert m.globals["z"] == 43


def test_load_missing_symbol():
    loaded = Module("m.star")
    loaded.globals["x"] = 1
    loaded.freeze()

    def loader(name):
        return loaded

    with pytest.raises(EvalError, match="not found in module"):
        starlark.exec_file('load("m.star", "missing")\n', loader=loader)


def test_load_chained():
    """Two-level load: a loads b, then we load a."""
    b_module = Module("b.star")
    b_module.globals["B_CONST"] = 100
    b_module.freeze()

    cache = {"b.star": b_module}

    def loader(name):
        if name in cache:
            return cache[name]
        if name == "a.star":
            mod = starlark.exec_file(
                'load("b.star", "B_CONST")\nA_CONST = B_CONST * 2\n',
                filename="a.star",
                loader=loader,
            )
            mod.freeze()
            cache[name] = mod
            return mod
        raise AssertionError(f"unexpected load: {name}")

    m = starlark.exec_file('load("a.star", "A_CONST")\nz = A_CONST\n', loader=loader)
    assert m.globals["z"] == 200
