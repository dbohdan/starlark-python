"""Method dispatch for Starlark values.

`get_method(value, name)` returns a bound `BuiltinFunction` for the named
method, or `None` if the value has no such method. Phases 8 and 9 expand
the method tables for strings and collections.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .values import BuiltinFunction, Dict, Range, StarlarkList, StarlarkSet


def _bind(name: str, value: Any, impl: Callable) -> BuiltinFunction:
    return BuiltinFunction(name=f"{type(value).__name__}.{name}", impl=lambda *a, **kw: impl(value, *a, **kw))


# Built per-type method tables. Each maps name -> (callable taking the
# receiver as first arg and returning the result).

_STRING_METHODS: dict[str, Callable] = {}
_LIST_METHODS: dict[str, Callable] = {}
_DICT_METHODS: dict[str, Callable] = {}
_SET_METHODS: dict[str, Callable] = {}


def register_string_method(name: str, fn: Callable) -> None:
    _STRING_METHODS[name] = fn


def register_list_method(name: str, fn: Callable) -> None:
    _LIST_METHODS[name] = fn


def register_dict_method(name: str, fn: Callable) -> None:
    _DICT_METHODS[name] = fn


def register_set_method(name: str, fn: Callable) -> None:
    _SET_METHODS[name] = fn


def get_method(value: Any, name: str) -> BuiltinFunction | None:
    table: dict | None = None
    if isinstance(value, str):
        table = _STRING_METHODS
    elif isinstance(value, StarlarkList):
        table = _LIST_METHODS
    elif isinstance(value, Dict):
        table = _DICT_METHODS
    elif isinstance(value, StarlarkSet):
        table = _SET_METHODS
    elif isinstance(value, Range):
        return None  # range has no methods
    if table is None:
        return None
    impl = table.get(name)
    if impl is None:
        return None
    return _bind(name, value, impl)


__all__ = [
    "get_method",
    "register_dict_method",
    "register_list_method",
    "register_set_method",
    "register_string_method",
]
