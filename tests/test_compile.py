"""Phase 3: `compile(source)` returns a `Program` runnable many times.

Validates:
- Auto-detection of expression vs file.
- `mode="expression"` / `mode="file"` overrides.
- Multiple runs against fresh modules.
- Resource limits applied per-run, not per-compile.
- Eval/exec mismatch raises a clear error.
- The existing `eval()` and `exec_file()` wrappers still work.
"""

from __future__ import annotations

import pytest

import starlark
from starlark import (
    BuiltinFunction,
    Module,
    Program,
    StarlarkSyntaxException,
    StepLimitExceeded,
    compile,
    from_value,
)

# --------------------------------------------------------------- compile


def test_compile_expression_auto():
    p = compile("1 + 2")
    assert isinstance(p, Program)
    assert p.is_expression
    assert p.eval() == 3


def test_compile_file_auto():
    p = compile("x = 1\ny = 2\n")
    assert not p.is_expression
    m = p.exec()
    assert m.get("x") == 1
    assert m.get("y") == 2


def test_compile_single_call_classified_as_expression():
    """Bare `f()` is a valid expression — auto mode picks expression."""
    p = compile("len([1, 2, 3])")
    assert p.is_expression


def test_compile_mode_file_forces_file_mode():
    """A bare expression compiled in file mode runs as an expression
    statement (result discarded). This is what exec_file uses internally."""
    p = compile("len([1, 2, 3])", mode="file")
    assert not p.is_expression
    m = p.exec()
    assert isinstance(m, Module)


def test_compile_mode_expression_rejects_files():
    with pytest.raises(StarlarkSyntaxException):
        compile("x = 1\n", mode="expression")


def test_compile_unknown_mode_raises():
    with pytest.raises(ValueError, match="unknown mode"):
        compile("1", mode="bogus")


def test_compile_raises_on_syntax_error():
    with pytest.raises(StarlarkSyntaxException):
        compile("def 1: pass")


# --------------------------------------------------------------- reuse


def test_program_eval_runs_many_times_with_fresh_state():
    """Each `.eval()` call creates a fresh Module, so module-globals
    don't leak between runs."""
    p = compile("[x * 2 for x in data]")
    assert from_value(p.eval(data=[1, 2, 3])) == [2, 4, 6]
    assert from_value(p.eval(data=[10])) == [20]
    assert from_value(p.eval(data=[])) == []


def test_program_exec_runs_many_times_with_fresh_modules():
    p = compile("z = x + y\n")
    m1 = p.exec(predeclared={"x": 1, "y": 2})
    m2 = p.exec(predeclared={"x": 10, "y": 20})
    assert m1.get("z") == 3
    assert m2.get("z") == 30
    # Modules are distinct.
    assert m1 is not m2
    assert m1.mutability is not m2.mutability


def test_program_exec_can_be_run_with_different_envs():
    """The resolver re-runs each call, so a name introduced in one
    `predeclared=` works without polluting another call."""
    p = compile("answer = greet(who)\n")
    m1 = p.exec(
        predeclared={
            "greet": BuiltinFunction(name="greet", impl=lambda x: "hi " + x),
            "who": "world",
        }
    )
    assert m1.get("answer") == "hi world"
    m2 = p.exec(
        predeclared={
            "greet": BuiltinFunction(name="greet", impl=lambda x: "bye " + x),
            "who": "earth",
        }
    )
    assert m2.get("answer") == "bye earth"


# --------------------------------------------------------------- mismatched call


def test_program_eval_on_file_raises():
    p = compile("x = 1\n")
    with pytest.raises(ValueError, match="\\.exec\\(\\)"):
        p.eval()


def test_program_exec_on_expression_raises():
    p = compile("1 + 1", mode="expression")
    with pytest.raises(ValueError, match="\\.eval\\(\\)"):
        p.exec()


# --------------------------------------------------------------- limits


def test_resource_limits_apply_per_run():
    p = compile("x = 0\nfor i in range(1000):\n    x = x + i\n")
    # Tiny budget — should trip.
    with pytest.raises(StepLimitExceeded):
        p.exec(max_steps=10)
    # Plenty of budget — should succeed.
    m = p.exec(max_steps=1_000_000)
    assert m.get("x") == sum(range(1000))


# --------------------------------------------------------------- legacy wrappers


def test_legacy_eval_still_works():
    assert starlark.eval("2 + 3") == 5


def test_legacy_eval_accepts_env_kwargs():
    assert starlark.eval("x * 2", x=21) == 42


def test_legacy_exec_file_still_works():
    m = starlark.exec_file("x = 41\ny = x + 1\n")
    assert m.get("y") == 42


def test_legacy_exec_file_handles_bare_call():
    """Regression: a single-line bare call must run as a file (its own
    statement), not as an expression-mode Program. Otherwise the
    conformance suite — which is full of `assert_eq(...)` chunks —
    would break."""
    captured = []
    m = starlark.exec_file(
        "log(42)\n",
        predeclared={"log": BuiltinFunction(name="log", impl=captured.append)},
    )
    assert isinstance(m, Module)
    assert captured == [42]


# --------------------------------------------------------------- remarshal


def test_remarshal_pattern():
    """Simulate the remarshal compile-once pattern using ONLY the
    public API. No `starlark.eval.*` imports needed."""
    from starlark import Mutability, from_value, to_value

    program = compile("[x * 2 for x in data]")

    def transform(doc):
        m = Mutability("transform")
        try:
            return from_value(program.eval(data=to_value(doc, mutability=m)))
        finally:
            m.freeze()

    assert transform([1, 2, 3]) == [2, 4, 6]
    assert transform([10, 20]) == [20, 40]
    assert transform([]) == []
