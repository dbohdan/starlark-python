"""Tests for the resolver."""

from __future__ import annotations

from starlark.syntax import Lexer, ast, parse, resolve
from starlark.syntax.resolver import Binding, Scope


def parse_and_resolve(source: str, predeclared=frozenset(), universal=None):
    if universal is None:
        universal = frozenset({"None", "True", "False", "len", "print"})
    f = parse(source)
    assert not f.errors, [str(e) for e in f.errors]
    locs = Lexer(source).locs
    resolve(f, locs, predeclared=predeclared, universal=universal)
    return f


def find_idents(node) -> list[ast.Identifier]:
    out: list[ast.Identifier] = []
    _walk(node, out)
    return out


def _walk(node, out):
    if isinstance(node, ast.Identifier):
        out.append(node)
    elif isinstance(node, list):
        for x in node:
            _walk(x, out)
    elif hasattr(node, "__slots__"):
        for s in node.__slots__:
            _walk(getattr(node, s, None), out)


def test_simple_global_assignment():
    f = parse_and_resolve("x = 1\nprint(x)\n")
    assert "x" in f.globals
    by_name: dict[str, list[ast.Identifier]] = {}
    for i in find_idents(f.statements):
        if isinstance(i.binding, Binding):
            by_name.setdefault(i.name, []).append(i)
    assert all(b.binding is not None and b.binding.scope == Scope.UNIVERSAL for b in by_name["print"])
    assert all(b.binding is not None and b.binding.scope == Scope.GLOBAL for b in by_name["x"])


def test_function_locals():
    f = parse_and_resolve(
        "def f(x):\n"
        "    y = x + 1\n"
        "    return y\n"
    )
    [def_stmt] = f.statements
    assert isinstance(def_stmt, ast.DefStatement)
    assert set(def_stmt.locals) == {"x", "y"}
    assert def_stmt.freevars == []


def test_closure_freevars():
    f = parse_and_resolve(
        "def outer():\n"
        "    a = 1\n"
        "    def inner():\n"
        "        return a\n"
        "    return inner\n"
    )
    outer = f.statements[0]
    assert isinstance(outer, ast.DefStatement)
    inner = outer.body[1]
    assert isinstance(inner, ast.DefStatement)
    assert "a" in inner.freevars


def test_break_outside_loop():
    f = parse("break\n")
    locs = Lexer("break\n").locs
    resolve(f, locs)
    assert any("outside of a loop" in e.message for e in f.errors)


def test_return_outside_function():
    f = parse("return 1\n")
    locs = Lexer("return 1\n").locs
    resolve(f, locs)
    assert any("outside of a function" in e.message for e in f.errors)


def test_duplicate_parameter():
    src = "def f(x, x): pass\n"
    f = parse(src)
    locs = Lexer(src).locs
    resolve(f, locs)
    assert any("duplicate parameter" in e.message for e in f.errors)


def test_default_after_nondefault():
    src = "def f(x=1, y): pass\n"
    f = parse(src)
    locs = Lexer(src).locs
    resolve(f, locs)
    assert any(
        "non-default parameter follows default" in e.message for e in f.errors
    )


def test_reassign_universal_is_error():
    src = "True = 1\n"
    f = parse(src)
    locs = Lexer(src).locs
    resolve(f, locs)
    assert any("cannot reassign True" in e.message for e in f.errors)


def test_for_loop_var_is_local():
    f = parse_and_resolve(
        "def f(xs):\n"
        "    for i in xs:\n"
        "        print(i)\n"
    )
    def_stmt = f.statements[0]
    assert isinstance(def_stmt, ast.DefStatement)
    assert "i" in def_stmt.locals


def test_comprehension_scope():
    f = parse_and_resolve(
        "result = [x*2 for x in xs]\n"
        "xs = [1, 2, 3]\n"
    )
    # `x` should not pollute module globals.
    assert "x" not in f.globals
    assert "result" in f.globals
    assert "xs" in f.globals


def test_load_binding_creates_global():
    f = parse_and_resolve('load("m.bzl", "foo", bar = "baz")\n')
    assert "foo" in f.globals
    assert "bar" in f.globals


def test_lambda_locals():
    f = parse_and_resolve("f = lambda x: x + 1\n")
    assign = f.statements[0]
    assert isinstance(assign, ast.AssignmentStatement)
    lam = assign.rhs
    assert isinstance(lam, ast.LambdaExpression)
    assert "x" in lam.locals
