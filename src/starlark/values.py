"""Public value types and Python <-> Starlark conversion helpers.

This module is the host integration surface for embedding Starlark in a
Python application:

- Re-exports the runtime value classes (`Dict`, `StarlarkList`, `StarlarkSet`,
  `Range`, `BuiltinFunction`) and the `Mutability` token, so hosts do not
  need to reach into `starlark.eval.*`.

- Provides `to_value` / `from_value` for recursively converting Python data
  structures to and from Starlark values.

The primitive types (`bool`, `int`, `float`, `str`, `None`, `tuple`,
`bytes`, `datetime.date` / `.time` / `.datetime`) round-trip as themselves
because the evaluator uses Python natives for them. Only the four mutable
container types and `Range` need wrappers.

Note: `bytes` is not a Starlark type. Python `bytes` values pass through
the evaluator as opaque objects, usable only by host-provided builtins.
"""

from __future__ import annotations

import datetime as _datetime
from typing import Any

from .eval.mutability import IMMUTABLE, Mutability
from .eval.values import (
    BuiltinFunction,
    Dict,
    Range,
    StarlarkList,
    StarlarkSet,
    check_hashable,
    equal,
    less_than,
    repr_starlark,
    starlark_type,
    str_starlark,
    truth,
)


class UnsupportedTypeError(TypeError):
    """`to_value` / `from_value` met a value it cannot convert."""


_SCALAR_TYPES: tuple[type, ...] = (
    bool,
    int,
    float,
    str,
    bytes,
    _datetime.date,  # also covers datetime.datetime
    _datetime.time,
)


def to_value(py_value: Any, *, mutability: Mutability | None = None) -> Any:
    """Recursively wrap a Python value as a Starlark value.

    Containers (`dict`, `list`, `tuple`) are converted to `Dict`,
    `StarlarkList`, and Python `tuple` respectively, all sharing the same
    `mutability` token. Tuples stay as tuples (Starlark's tuple is the
    Python tuple). Primitive scalars pass through unchanged.

    If `mutability` is `None`, a fresh `Mutability("to_value")` is created
    and frozen — the resulting tree is read-only. To produce a mutable
    tree, pass a `Module.mutability` (or any unfrozen `Mutability`).

    Raises `UnsupportedTypeError` for anything that isn't a recognized
    Python primitive, container, or already a Starlark value.
    """
    if mutability is None:
        mutability = Mutability("to_value")
        mutability.freeze()
    return _to_value(py_value, mutability)


def _to_value(value: Any, mut: Mutability) -> Any:
    if value is None:
        return None
    if isinstance(value, _SCALAR_TYPES):
        return value
    if isinstance(value, dict):
        return Dict(
            {k: _to_value(v, mut) for k, v in value.items()},
            mutability=mut,
        )
    if isinstance(value, list):
        return StarlarkList(
            [_to_value(v, mut) for v in value],
            mutability=mut,
        )
    if isinstance(value, tuple):
        return tuple(_to_value(v, mut) for v in value)
    # Already a Starlark value? Return it as-is. Hosts that build trees
    # incrementally should be able to nest pre-wrapped values.
    if isinstance(value, (Dict, StarlarkList, StarlarkSet, Range, BuiltinFunction)):
        return value
    raise UnsupportedTypeError(
        f"to_value: cannot convert Python value of type {type(value).__name__!r}"
    )


def from_value(sv: Any) -> Any:
    """Recursively unwrap a Starlark value to plain Python data.

    `Dict` becomes `dict`, `StarlarkList` becomes `list`, `Range` becomes
    `list`, and `tuple` becomes `list` — the conversion is intentionally
    lossy on container kind so the result is a clean Python data tree.

    Primitive scalars (`None`, `bool`, `int`, `float`, `str`, `bytes`,
    `datetime` types) pass through.

    `StarlarkSet` raises `UnsupportedTypeError`: ordering is
    insertion-defined and not what most callers want when serializing.
    Convert explicitly with `sorted(s)` or `list(s)` in Starlark.
    Functions and arbitrary host objects also raise.
    """
    if sv is None:
        return None
    if isinstance(sv, _SCALAR_TYPES):
        return sv
    if isinstance(sv, Dict):
        return {from_value(k): from_value(v) for k, v in sv.items()}
    if isinstance(sv, StarlarkList):
        return [from_value(v) for v in sv]
    if isinstance(sv, tuple):
        return [from_value(v) for v in sv]
    if isinstance(sv, Range):
        return list(sv)
    if isinstance(sv, StarlarkSet):
        raise UnsupportedTypeError(
            "from_value: got a Starlark set; convert it explicitly with "
            "sorted(s) or list(s) in Starlark before returning"
        )
    type_name = getattr(sv, "_starlark_type", type(sv).__name__)
    raise UnsupportedTypeError(
        f"from_value: cannot convert Starlark value of type {type_name!r}"
    )


# --------------------------------------------------------------- namespace


class Namespace:
    """A named bundle of attribute-accessed values exposed to Starlark.

    Implements the protocol the evaluator already uses for the `json`
    module and conformance test `struct`s: a `fields` dict mapping
    attribute names to values, plus `_starlark_type` for the type name
    that appears in error messages and `type(x)` calls.

    Construct via `starlark.namespace(name, fields)` rather than
    instantiating directly.
    """

    __slots__ = ("_starlark_type", "fields")

    def __init__(self, name: str, fields: dict[str, Any]) -> None:
        self._starlark_type = name
        self.fields = fields

    def __repr__(self) -> str:
        return f"<namespace {self._starlark_type}>"


def namespace(name: str, fields: dict[str, Any]) -> Namespace:
    """Build a namespace value: a struct-like object exposing `fields`
    as attributes accessible from Starlark.

    Python callables in `fields` are auto-wrapped as `BuiltinFunction`s
    with qualified names of the form `"{name}.{key}"`. Already-wrapped
    `BuiltinFunction`s pass through unchanged. Non-callable values are
    stored verbatim, so `namespace("config", {"version": "1.0"})` works
    and exposes `config.version` to Starlark code.

    Example:
        ns = namespace("remarshal", {
            "bytes_to_str": lambda b, encoding="utf-8": b.decode(encoding),
            "version": "0.5.0",
        })
        starlark.eval("remarshal.bytes_to_str(data)", remarshal=ns, data=b"hi")
    """
    wrapped: dict[str, Any] = {}
    for key, value in fields.items():
        if isinstance(value, BuiltinFunction):
            wrapped[key] = value
        elif callable(value):
            wrapped[key] = BuiltinFunction(name=f"{name}.{key}", impl=value)
        else:
            wrapped[key] = value
    return Namespace(name, wrapped)


__all__ = [
    "IMMUTABLE",
    "BuiltinFunction",
    "Dict",
    "Mutability",
    "Namespace",
    "Range",
    "StarlarkList",
    "StarlarkSet",
    "UnsupportedTypeError",
    "check_hashable",
    "equal",
    "from_value",
    "less_than",
    "namespace",
    "repr_starlark",
    "starlark_type",
    "str_starlark",
    "to_value",
    "truth",
]
