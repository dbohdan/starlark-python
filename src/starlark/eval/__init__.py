"""Starlark runtime: values, mutability, evaluator.

Mirrors `net.starlark.java.eval`.
"""

# Side-effect: register string and collection methods so attribute access
# resolves them.
from . import collection_methods as _collection_methods  # noqa: F401
from . import string_methods as _string_methods  # noqa: F401
from .errors import CallFrame, EvalError, errorf
from .module import Module
from .mutability import IMMUTABLE, Mutability
from .values import (
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

__all__ = [
    "IMMUTABLE",
    "BuiltinFunction",
    "CallFrame",
    "Dict",
    "EvalError",
    "Module",
    "Mutability",
    "Range",
    "StarlarkList",
    "StarlarkSet",
    "check_hashable",
    "equal",
    "errorf",
    "less_than",
    "repr_starlark",
    "starlark_type",
    "str_starlark",
    "truth",
]
