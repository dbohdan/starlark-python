"""Phase 4: `starlark.namespace(name, fields)` builds the
`fields`-dict + `_starlark_type` object protocol that the evaluator
already uses for the `json` builtin and conformance test structs.

This is the supported way for hosts to expose a bundle of related
helpers (e.g. `remarshal.bytes_to_str`, `remarshal.iso_to_datetime`)
without hand-rolling the protocol every time.
"""

from __future__ import annotations

import pytest

import starlark
from starlark import (
    BuiltinFunction,
    Module,
    Namespace,
    StarlarkSyntaxException,
    namespace,
)

# --------------------------------------------------------------- shape


def test_namespace_returns_namespace_instance():
    ns = namespace("foo", {"x": 1})
    assert isinstance(ns, Namespace)
    assert ns._starlark_type == "foo"


def test_namespace_repr_includes_name():
    ns = namespace("config", {})
    assert "config" in repr(ns)


def test_namespace_fields_dict_is_isolated_copy():
    """Mutating the input dict after construction must not affect the
    namespace."""
    src: dict = {"x": 1}
    ns = namespace("foo", src)
    src["y"] = 2
    assert "y" not in ns.fields


# --------------------------------------------------------------- callable wrapping


def test_namespace_wraps_callables_as_builtin_functions():
    def greet(name):
        return "hi " + name

    ns = namespace("ns", {"greet": greet})
    fn = ns.fields["greet"]
    assert isinstance(fn, BuiltinFunction)
    assert fn.name == "ns.greet"


def test_namespace_passes_through_already_wrapped_builtins():
    inner = BuiltinFunction(name="custom.name", impl=lambda: 42)
    ns = namespace("ns", {"f": inner})
    # Pre-wrapped value passes through unchanged.
    assert ns.fields["f"] is inner
    assert ns.fields["f"].name == "custom.name"


def test_namespace_stores_non_callable_values_verbatim():
    ns = namespace("config", {"version": "1.0", "debug": True, "limit": 100})
    assert ns.fields["version"] == "1.0"
    assert ns.fields["debug"] is True
    assert ns.fields["limit"] == 100


# --------------------------------------------------------------- evaluator integration


def test_namespace_attribute_access_from_starlark():
    ns = namespace("ns", {"answer": 42})
    assert starlark.eval("ns.answer", ns=ns) == 42


def test_namespace_callable_attribute_from_starlark():
    ns = namespace("math2", {"double": lambda x: x * 2})
    assert starlark.eval("math2.double(21)", math2=ns) == 42


def test_namespace_function_with_default_kwargs():
    def encode(s, *, encoding="utf-8"):
        return s.encode(encoding)

    ns = namespace("text", {"encode": encode})
    result = starlark.eval('text.encode("hello")', text=ns)
    assert result == b"hello"


def test_namespace_via_predeclared_in_exec_file():
    ns = namespace("util", {"plus_one": lambda x: x + 1})
    m = starlark.exec_file(
        "result = util.plus_one(41)\n",
        predeclared={"util": ns},
    )
    assert isinstance(m, Module)
    assert m.get("result") == 42


def test_namespace_unknown_attribute_raises():
    ns = namespace("ns", {"x": 1})
    with pytest.raises(starlark.EvalError, match=r"no attribute|has no field"):
        starlark.eval("ns.missing", ns=ns)


# --------------------------------------------------------------- json round-trip


def test_namespace_works_with_json_encode():
    """The json module's encoder consumes the same `fields` protocol,
    so namespaces serialize cleanly."""
    ns = namespace("user", {"name": "Ada", "age": 36})
    result = starlark.eval('json.encode(u)', u=ns)
    # json.encode sorts keys lexicographically.
    assert result == '{"age":36,"name":"Ada"}'


# --------------------------------------------------------------- remarshal pattern


def test_remarshal_helper_module_pattern():
    """End-to-end: simulate what remarshal does with its
    `_make_remarshal_module` helper, but using the public
    namespace() API instead of hand-rolling the protocol."""
    import base64

    helpers = namespace(
        "remarshal",
        {
            "bytes_to_str": lambda b, encoding="utf-8": b.decode(encoding),
            "str_to_bytes": lambda s, encoding="utf-8": s.encode(encoding),
            "bytes_to_base64": lambda b: base64.b64encode(b).decode("ascii"),
        },
    )

    # Each helper is a BuiltinFunction with a remarshal-prefixed name.
    assert helpers.fields["bytes_to_str"].name == "remarshal.bytes_to_str"

    program = starlark.compile("remarshal.bytes_to_str(data)")
    assert program.eval(remarshal=helpers, data=b"hello") == "hello"

    program2 = starlark.compile("remarshal.bytes_to_base64(data)")
    assert program2.eval(remarshal=helpers, data=b"\x00\x01\x02") == "AAEC"


# --------------------------------------------------------------- parser sanity


def test_namespace_does_not_introduce_parser_keyword():
    """Sanity: 'namespace' is a Python identifier, not a Starlark
    keyword. Starlark code can use it as a name."""
    m = starlark.exec_file("namespace = 1\n")
    assert m.get("namespace") == 1
    # And the parser doesn't choke on it as an argument.
    try:
        starlark.exec_file("def f(namespace):\n    return namespace\n")
    except StarlarkSyntaxException:
        pytest.fail("'namespace' should not be a reserved word in Starlark")
