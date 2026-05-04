"""Starlark runtime value classes.

We use Python natives where possible:

- `None`        — the Starlark None.
- `bool`        — bool. (NB: `True == 1` per Python; matches the Java reference,
                  which uses `Boolean.equals`.)
- `int`         — Python int. Arbitrary precision; no overflow.
- `float`       — Python float (IEEE-754 64-bit).
- `str`         — Python str. Indexed by code point (see README).
- `tuple`       — Python tuple (immutable).

Mutable collections wrap a Python container plus a `Mutability` ref:

- `StarlarkList`, `Dict`, `StarlarkSet`.

Functions:

- `BuiltinFunction` for Python-implemented builtins.
- `StarlarkFunction` for user-defined `def` / `lambda` (lives in `function.py`).

`Range` is a lazy iterable; `bytes` is intentionally not implemented
(neither is the Java reference of any version we target).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from .errors import EvalError
from .mutability import IMMUTABLE, Mutability

# --------------------------------------------------------------- type names


def starlark_type(value: Any) -> str:
    """Returns the Starlark type name of a value, as `type(x)` would."""
    if value is None:
        return "NoneType"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, tuple):
        return "tuple"
    if isinstance(value, StarlarkList):
        return "list"
    if isinstance(value, Dict):
        return "dict"
    if isinstance(value, StarlarkSet):
        return "set"
    if isinstance(value, Range):
        return "range"
    if isinstance(value, BuiltinFunction):
        return "builtin_function_or_method"
    type_name = getattr(value, "_starlark_type", None)
    if type_name is not None:
        return type_name
    return type(value).__name__


# --------------------------------------------------------------- truth


def truth(value: Any) -> bool:
    """Starlark truth value. Mirrors Starlark.truth in Java."""
    if value is None or value is False:
        return False
    if value is True:
        return True
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return len(value) != 0
    if isinstance(value, tuple):
        return len(value) != 0
    if isinstance(value, (StarlarkList, Dict, StarlarkSet)):
        return len(value) != 0
    if isinstance(value, Range):
        return len(value) != 0
    return True


# --------------------------------------------------------------- mutable list


class StarlarkList:
    """A Starlark list: a mutable sequence of values."""

    __slots__ = ("_data", "mutability")

    _starlark_type = "list"

    def __init__(self, items: list | None = None, mutability: Mutability | None = None) -> None:
        self._data: list = list(items) if items else []
        self.mutability = mutability if mutability is not None else IMMUTABLE

    # ----- read-only ops

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator:
        return iter(self._data)

    def __contains__(self, item: Any) -> bool:
        return any(equal(x, item) for x in self._data)

    def __getitem__(self, idx):
        # Caller is expected to use evaluator helpers for slicing/index;
        # this is for internal use.
        return self._data[idx]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StarlarkList):
            return NotImplemented
        if len(self) != len(other):
            return False
        return all(equal(a, b) for a, b in zip(self._data, other._data))

    def __ne__(self, other: object) -> bool:
        eq = self.__eq__(other)
        return NotImplemented if eq is NotImplemented else not eq

    def __hash__(self):
        raise EvalError("unhashable type: 'list'")

    # ----- mutating ops

    def append(self, value: Any) -> None:
        self.mutability.check("list")
        self._data.append(value)

    def extend(self, items) -> None:
        self.mutability.check("list")
        # Cheap pre-check for known-size iterables to avoid OOM on hostile input.
        try:
            n = len(items)
        except TypeError:
            n = 0
        if n > (1 << 24):
            from .errors import EvalError as _E
            raise _E(f"excessive capacity requested: {n} elements")
        for x in items:
            self._data.append(x)

    def insert(self, index: int, value: Any) -> None:
        self.mutability.check("list")
        self._data.insert(index, value)

    def pop(self, index: int = -1) -> Any:
        self.mutability.check("list")
        return self._data.pop(index)

    def remove_value(self, value: Any) -> None:
        self.mutability.check("list")
        for i, x in enumerate(self._data):
            if equal(x, value):
                del self._data[i]
                return
        raise EvalError(f"item {repr_starlark(value)!s} not found in list")

    def clear(self) -> None:
        self.mutability.check("list")
        self._data.clear()

    def index_of(self, value: Any, start: int = 0, end: int | None = None) -> int:
        n = len(self._data)
        if end is None:
            end = n
        if start < 0:
            start = max(0, n + start)
        if end < 0:
            end = max(0, n + end)
        for i in range(start, min(end, n)):
            if equal(self._data[i], value):
                return i
        raise EvalError(f"item {repr_starlark(value)!s} not found in list")

    def count_of(self, value: Any) -> int:
        return sum(1 for x in self._data if equal(x, value))

    def __setitem__(self, idx, value) -> None:
        self.mutability.check("list")
        self._data[idx] = value

    def __delitem__(self, idx) -> None:
        self.mutability.check("list")
        del self._data[idx]


# --------------------------------------------------------------- dict


class Dict:
    """A Starlark dict: an ordered, mutable map. Insertion order preserved."""

    __slots__ = ("_data", "mutability")

    _starlark_type = "dict"

    def __init__(
        self,
        items: dict | None = None,
        mutability: Mutability | None = None,
    ) -> None:
        # Python 3.7+ dicts preserve insertion order, which matches Starlark.
        self._data: dict = dict(items) if items else {}
        self.mutability = mutability if mutability is not None else IMMUTABLE

    # ----- read-only

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator:
        return iter(self._data)

    def __contains__(self, key: Any) -> bool:
        check_hashable(key)
        return key in self._data

    def __getitem__(self, key: Any) -> Any:
        if key not in self._data:
            raise EvalError(f"KeyError: {repr_starlark(key)}")
        return self._data[key]

    def get(self, key: Any, default: Any = None) -> Any:
        check_hashable(key)
        return self._data.get(key, default)

    def keys(self) -> list:
        return list(self._data.keys())

    def values(self) -> list:
        return list(self._data.values())

    def items(self) -> list:
        return [(k, v) for k, v in self._data.items()]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Dict):
            return NotImplemented
        if len(self) != len(other):
            return False
        for k, v in self._data.items():
            if k not in other._data:
                return False
            if not equal(v, other._data[k]):
                return False
        return True

    def __ne__(self, other: object) -> bool:
        eq = self.__eq__(other)
        return NotImplemented if eq is NotImplemented else not eq

    def __hash__(self):
        raise EvalError("unhashable type: 'dict'")

    # ----- mutating

    def __setitem__(self, key: Any, value: Any) -> None:
        self.mutability.check("dict")
        check_hashable(key)
        self._data[key] = value

    def __delitem__(self, key: Any) -> None:
        self.mutability.check("dict")
        if key not in self._data:
            raise EvalError(f"KeyError: {repr_starlark(key)}")
        del self._data[key]

    def update(self, other) -> None:
        self.mutability.check("dict")
        if isinstance(other, Dict):
            for k, v in other._data.items():
                self._data[k] = v
        elif isinstance(other, dict):
            for k, v in other.items():
                self._data[k] = v
        else:
            for k, v in other:
                check_hashable(k)
                self._data[k] = v

    def setdefault(self, key: Any, default: Any) -> Any:
        check_hashable(key)
        # Always check mutability — a frozen dict rejects setdefault even if
        # the key already exists (matches the Java reference's behavior).
        self.mutability.check("dict")
        if key in self._data:
            return self._data[key]
        self._data[key] = default
        return default

    def pop(self, key: Any, *default) -> Any:
        check_hashable(key)
        # Check mutability before reading: even if key is missing and we'd
        # return the default, calling pop on a frozen dict is an error.
        self.mutability.check("dict")
        if key in self._data:
            return self._data.pop(key)
        if default:
            return default[0]
        raise EvalError(f"KeyError: {repr_starlark(key)}")

    def popitem(self) -> tuple:
        self.mutability.check("dict")
        if not self._data:
            raise EvalError("empty dictionary")
        # Starlark popitem is FIFO (first-inserted), unlike Python's LIFO.
        key = next(iter(self._data))
        value = self._data.pop(key)
        return (key, value)

    def clear(self) -> None:
        self.mutability.check("dict")
        self._data.clear()


# --------------------------------------------------------------- set


class StarlarkSet:
    """A Starlark set: insertion-ordered set of hashable values.

    Like Dict, we use Python's dict-with-sentinel-values trick to preserve
    insertion order, since Python's built-in `set` does not.
    """

    __slots__ = ("_data", "mutability")

    _starlark_type = "set"

    def __init__(
        self,
        items: Any | None = None,
        mutability: Mutability | None = None,
    ) -> None:
        self._data: dict = {}
        if items is not None:
            for x in items:
                check_hashable(x)
                self._data[x] = None
        self.mutability = mutability if mutability is not None else IMMUTABLE

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator:
        return iter(self._data)

    def __contains__(self, item: Any) -> bool:
        return item in self._data

    def add(self, item: Any) -> None:
        self.mutability.check("set")
        check_hashable(item)
        self._data[item] = None

    def discard(self, item: Any) -> None:
        self.mutability.check("set")
        self._data.pop(item, None)

    def remove_value(self, item: Any) -> None:
        self.mutability.check("set")
        if item not in self._data:
            raise EvalError(f"item not in set: {repr_starlark(item)}")
        del self._data[item]

    def clear(self) -> None:
        self.mutability.check("set")
        self._data.clear()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StarlarkSet):
            return NotImplemented
        return self._data.keys() == other._data.keys()

    def __ne__(self, other: object) -> bool:
        eq = self.__eq__(other)
        return NotImplemented if eq is NotImplemented else not eq

    def __hash__(self):
        raise EvalError("unhashable type: 'set'")


# --------------------------------------------------------------- range


@dataclass(frozen=True, slots=True)
class Range:
    """An immutable lazy integer sequence. Mirrors Java's RangeList."""

    start: int
    stop: int
    step: int

    _starlark_type = "range"

    def __post_init__(self):
        if self.step == 0:
            raise EvalError("step cannot be 0")

    def __len__(self) -> int:
        if self.step > 0:
            return max(0, (self.stop - self.start + self.step - 1) // self.step)
        return max(0, (self.start - self.stop - self.step - 1) // -self.step)

    def __iter__(self) -> Iterator[int]:
        i = self.start
        if self.step > 0:
            while i < self.stop:
                yield i
                i += self.step
        else:
            while i > self.stop:
                yield i
                i += self.step

    def __contains__(self, value: Any) -> bool:
        if not isinstance(value, int) or isinstance(value, bool):
            return False
        if self.step > 0:
            if value < self.start or value >= self.stop:
                return False
        else:
            if value > self.start or value <= self.stop:
                return False
        return (value - self.start) % self.step == 0

    def __getitem__(self, index: int) -> int:
        n = len(self)
        if index < 0:
            index += n
        if index < 0 or index >= n:
            raise EvalError("range index out of range")
        return self.start + index * self.step

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Range):
            return NotImplemented
        n = len(self)
        if n != len(other):
            return False
        if n == 0:
            return True
        if self.start != other.start:
            return False
        if n == 1:
            return True
        return self.step == other.step

    def __ne__(self, other: object) -> bool:
        eq = self.__eq__(other)
        return NotImplemented if eq is NotImplemented else not eq

    def __hash__(self):
        raise EvalError("unhashable type: 'range'")


# --------------------------------------------------------------- builtin fn


@dataclass(slots=True)
class BuiltinFunction:
    """A callable implemented in Python and exposed to Starlark code."""

    name: str
    impl: Callable[..., Any]
    # Used by repr; e.g. "list" for list.append-like methods.
    self_repr: str | None = None

    _starlark_type = "builtin_function_or_method"

    def __call__(self, *args, **kwargs):
        return self.impl(*args, **kwargs)


# --------------------------------------------------------------- helpers


def check_hashable(value: Any) -> None:
    """Raise EvalError if `value` cannot be used as a dict key or set member."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return
    if isinstance(value, tuple):
        for x in value:
            check_hashable(x)
        return
    if isinstance(value, Range):
        return
    # User-defined Starlark functions are hashable by identity.
    from .function import StarlarkFunction
    if isinstance(value, StarlarkFunction):
        return
    raise EvalError(f"unhashable type: '{starlark_type(value)}'")


_EQUAL_SEEN: list[set] = []


def equal(a: Any, b: Any) -> bool:
    """Starlark equality. Same-type structural; cross-numeric (int <-> float).

    Distinct types compare unequal. The bool/int special case follows the
    Java reference (which inherits Java's `Boolean.equals(Integer)` returning
    false), so `True == 1` is False in Starlark — matching the spec.

    Cycles between mutable values are handled by recording each pair we're
    currently comparing; a recurrence is treated as equal at that level.
    """
    if isinstance(a, (StarlarkList, Dict, StarlarkSet)) and isinstance(
        b, (StarlarkList, Dict, StarlarkSet)
    ):
        pair = (id(a), id(b))
        if not _EQUAL_SEEN:
            _EQUAL_SEEN.append(set())
        seen = _EQUAL_SEEN[-1]
        if pair in seen:
            return True
        seen.add(pair)
        try:
            return a == b
        finally:
            seen.discard(pair)
    if type(a) is type(b):
        return a == b
    # bool/int cross: spec says distinct — explicitly check before int/float.
    if isinstance(a, bool) or isinstance(b, bool):
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return False


def less_than(a: Any, b: Any) -> bool:
    """Starlark `<`. Same-type ordered; numeric int <-> float allowed.

    NaN sorts greater than every non-NaN value (matching Java's Double.compare).
    """
    if isinstance(a, bool) and isinstance(b, bool):
        return (not a) and b
    # Reject bool vs non-bool numeric per the spec.
    if isinstance(a, bool) or isinstance(b, bool):
        raise EvalError(
            f"unsupported comparison: {starlark_type(a)} < {starlark_type(b)}"
        )
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        # Handle NaN: NaN > everything, NaN == NaN.
        a_nan = isinstance(a, float) and a != a
        b_nan = isinstance(b, float) and b != b
        if a_nan and b_nan:
            return False
        if a_nan:
            return False  # NaN sorts to the end
        if b_nan:
            return True
        return a < b
    if isinstance(a, str) and isinstance(b, str):
        return a < b
    if isinstance(a, tuple) and isinstance(b, tuple):
        for x, y in zip(a, b):
            if not equal(x, y):
                return less_than(x, y)
        return len(a) < len(b)
    if isinstance(a, StarlarkList) and isinstance(b, StarlarkList):
        for x, y in zip(a, b):
            if not equal(x, y):
                return less_than(x, y)
        return len(a) < len(b)
    # Order-independent error message: report the pair sorted by type-name
    # so that `min(int, string)` and `min(string, int)` give the same text.
    types = sorted([starlark_type(a), starlark_type(b)])
    raise EvalError(
        f"unsupported comparison: {types[0]} <=> {types[1]}"
    )


# --------------------------------------------------------------- repr


def repr_starlark(value: Any, _seen: set | None = None) -> str:
    """Returns the canonical Starlark representation of a value (`repr(x)`)."""
    if _seen is None:
        _seen = set()
    # Cycle detection for mutable containers. Render the recursive
    # reference as a bare `...` so the surrounding container's brackets are
    # preserved (matches Java's CycleDetector behavior).
    if isinstance(value, (StarlarkList, Dict, StarlarkSet)):
        if id(value) in _seen:
            return "..."
        _seen = _seen | {id(value)}
    if value is None:
        return "None"
    if value is True:
        return "True"
    if value is False:
        return "False"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _float_repr(value)
    if isinstance(value, str):
        return _str_repr(value)
    if isinstance(value, tuple):
        if len(value) == 1:
            return f"({repr_starlark(value[0], _seen)},)"
        return "(" + ", ".join(repr_starlark(x, _seen) for x in value) + ")"
    if isinstance(value, StarlarkList):
        return "[" + ", ".join(repr_starlark(x, _seen) for x in value) + "]"
    if isinstance(value, Dict):
        return (
            "{"
            + ", ".join(
                f"{repr_starlark(k, _seen)}: {repr_starlark(v, _seen)}"
                for k, v in value.items()
            )
            + "}"
        )
    if isinstance(value, StarlarkSet):
        if len(value) == 0:
            return "set()"
        return "set([" + ", ".join(repr_starlark(x, _seen) for x in value) + "])"
    if isinstance(value, Range):
        if value.step == 1:
            return f"range({value.start}, {value.stop})"
        return f"range({value.start}, {value.stop}, {value.step})"
    if isinstance(value, BuiltinFunction):
        return f"<built-in function {value.name}>" if not value.self_repr else (
            f"<built-in method {value.name.split('.')[-1]} of {value.self_repr} value>"
        )
    # User-defined functions — let their __repr__ handle it.
    return repr(value)


def str_starlark(value: Any) -> str:
    """`str(x)`. Same as repr for most types, but plain text for strings."""
    if isinstance(value, str):
        return value
    return repr_starlark(value)


def _float_repr(x: float) -> str:
    if x != x:  # NaN
        return "nan"
    if x == float("inf"):
        return "+inf"
    if x == float("-inf"):
        return "-inf"
    # Match Python's float repr but ensure there's a decimal point.
    s = repr(x)
    if "." not in s and "e" not in s and "n" not in s and "i" not in s:
        s += ".0"
    return s


def _str_repr(s: str) -> str:
    # Choose double quotes unless the string contains one but no apostrophe.
    if '"' in s and "'" not in s:
        quote = "'"
    else:
        quote = '"'
    out = [quote]
    for ch in s:
        if ch == quote:
            out.append("\\" + quote)
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append("\\x%02x" % ord(ch))
        else:
            out.append(ch)
    out.append(quote)
    return "".join(out)


__all__ = [
    "BuiltinFunction",
    "Dict",
    "Range",
    "StarlarkList",
    "StarlarkSet",
    "check_hashable",
    "equal",
    "less_than",
    "repr_starlark",
    "starlark_type",
    "str_starlark",
    "truth",
]
