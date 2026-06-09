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

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .errors import EvalError
from .limits import (
    ALLOC_DICT_ENTRY,
    ALLOC_LIST_ELEM,
    ALLOC_RANGE,
    ALLOC_SET_ENTRY,
    MAX_NESTING_DEPTH,
    dict_alloc,
    list_alloc,
    set_alloc,
)
from .mutability import IMMUTABLE, Mutability


def _charge(n: int) -> None:
    """Charge `n` approximate bytes against the current Thread's heap counter.

    No-op if there is no current Thread (e.g. unit tests that build values
    directly). The contextvar lookup is the only per-allocation overhead;
    avoid hot-path imports by binding lazily.
    """
    # Local import to avoid a circular dependency at module load time
    # (builtins.py imports from values.py).
    from .builtins import _CURRENT_THREAD

    thread = _CURRENT_THREAD.get(None)
    if thread is not None:
        thread.add_allocs(n)


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

    def __init__(
        self, items: Sequence[Any] | None = None, mutability: Mutability | None = None
    ) -> None:
        self._data: list = list(items) if items else []
        self.mutability = mutability if mutability is not None else IMMUTABLE
        _charge(list_alloc(len(self._data)))

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
        return all(equal(a, b) for a, b in zip(self._data, other._data, strict=True))

    def __ne__(self, other: object) -> bool:
        eq = self.__eq__(other)
        return NotImplemented if eq is NotImplemented else not eq

    def __hash__(self):
        raise EvalError("unhashable type: 'list'")

    # ----- mutating ops

    def append(self, value: Any) -> None:
        self.mutability.check("list")
        self._data.append(value)
        _charge(ALLOC_LIST_ELEM)

    def extend(self, items) -> None:
        self.mutability.check("list")
        from .limits import MAX_CONTAINER_ELEMENTS, check_container_size

        # Pre-check for known-size iterables to avoid OOM on hostile input.
        try:
            n = len(items)
        except TypeError:
            n = None
        if n is not None:
            check_container_size(len(self._data) + n)
            self._data.extend(items)
            _charge(ALLOC_LIST_ELEM * n)
            return
        # Streaming case: cap as we go.
        added = 0
        for x in items:
            if len(self._data) >= MAX_CONTAINER_ELEMENTS:
                check_container_size(len(self._data) + 1)
            self._data.append(x)
            added += 1
        _charge(ALLOC_LIST_ELEM * added)

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


# All NaN instances collapse to this canonical one so they can be used as
# dict/set keys without the Python-default `nan != nan` quirk preventing
# lookup. (See the discussion in conformance/float.star.)
_NAN_KEY = float("nan")


def _normalize_key(k: Any) -> Any:
    """Return `k` with NaN floats canonicalized to a single instance."""
    if isinstance(k, float) and k != k:
        return _NAN_KEY
    return k


class Dict:
    """A Starlark dict: an ordered, mutable map. Insertion order preserved."""

    __slots__ = ("_data", "mutability")

    _starlark_type = "dict"

    def __init__(
        self,
        items: Mapping[Any, Any] | None = None,
        mutability: Mutability | None = None,
    ) -> None:
        # Python 3.7+ dicts preserve insertion order, which matches Starlark.
        self._data: dict = {}
        if items:
            for k, v in items.items():
                self._data[_normalize_key(k)] = v
        self.mutability = mutability if mutability is not None else IMMUTABLE
        _charge(dict_alloc(len(self._data)))

    # ----- read-only

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator:
        return iter(self._data)

    def __contains__(self, key: Any) -> bool:
        check_hashable(key)
        return _normalize_key(key) in self._data

    def __getitem__(self, key: Any) -> Any:
        nk = _normalize_key(key)
        if nk not in self._data:
            raise EvalError(f"KeyError: {repr_starlark(key)}")
        return self._data[nk]

    def get(self, key: Any, default: Any = None) -> Any:
        check_hashable(key)
        return self._data.get(_normalize_key(key), default)

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
        nk = _normalize_key(key)
        # Charge per new entry; updates of existing keys don't grow the dict.
        if nk not in self._data:
            _charge(ALLOC_DICT_ENTRY)
        self._data[nk] = value

    def __delitem__(self, key: Any) -> None:
        self.mutability.check("dict")
        nk = _normalize_key(key)
        if nk not in self._data:
            raise EvalError(f"KeyError: {repr_starlark(key)}")
        del self._data[nk]

    def update(self, other) -> None:
        self.mutability.check("dict")
        before = len(self._data)
        if isinstance(other, Dict):
            for k, v in other._data.items():
                self._data[_normalize_key(k)] = v
        elif isinstance(other, dict):
            for k, v in other.items():
                self._data[_normalize_key(k)] = v
        else:
            for k, v in other:
                check_hashable(k)
                self._data[_normalize_key(k)] = v
        added = len(self._data) - before
        if added:
            _charge(ALLOC_DICT_ENTRY * added)

    def setdefault(self, key: Any, default: Any) -> Any:
        check_hashable(key)
        # Always check mutability — a frozen dict rejects setdefault even if
        # the key already exists (matches the Java reference's behavior).
        self.mutability.check("dict")
        nk = _normalize_key(key)
        if nk in self._data:
            return self._data[nk]
        self._data[nk] = default
        _charge(ALLOC_DICT_ENTRY)
        return default

    def pop(self, key: Any, *default) -> Any:
        check_hashable(key)
        # Check mutability before reading: even if key is missing and we'd
        # return the default, calling pop on a frozen dict is an error.
        self.mutability.check("dict")
        nk = _normalize_key(key)
        if nk in self._data:
            return self._data.pop(nk)
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
        _charge(set_alloc(len(self._data)))

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator:
        return iter(self._data)

    def __contains__(self, item: Any) -> bool:
        return item in self._data

    def add(self, item: Any) -> None:
        self.mutability.check("set")
        check_hashable(item)
        if item not in self._data:
            _charge(ALLOC_SET_ENTRY)
        self._data[item] = None

    def discard(self, item: Any) -> None:
        self.mutability.check("set")
        self._data.pop(item, None)

    def remove_value(self, item: Any) -> None:
        self.mutability.check("set")
        if item not in self._data:
            raise EvalError(f"{repr_starlark(item)} not found")
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
        _charge(ALLOC_RANGE)

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


def _check_compare_depth(_depth: int) -> None:
    """Bound structural recursion in value comparison.

    `MAX_NESTING_DEPTH` is enforced statically (parser, evaluator AST walk,
    `repr_starlark`, ...), but a value can be built deep at runtime
    (`x = []` then `for i in range(N): x = [x]`). Comparing such a value
    (`x == x`, `x in [x]`, `sorted([x, x])`) would otherwise recurse into
    Python's call stack and leak a `RecursionError`. The cycle-detection
    set handles cyclic references; this catches the linear-deep case.
    """
    if _depth > MAX_NESTING_DEPTH:
        raise EvalError(f"value too deeply nested to compare (>{MAX_NESTING_DEPTH} levels)")


def _equal_containers(a: Any, b: Any, _depth: int) -> bool:
    """Element-wise equality for two Starlark containers, depth-threaded.

    Mirrors the per-type `__eq__` bodies but recurses through `equal` so the
    depth bound propagates. Uses explicit loops (no generator expressions) to
    keep the per-level Python frame count low, so the EvalError raised at the
    cap can unwind before CPython's own recursion limit is hit. Set elements
    are hashable scalars (never nested containers), so set equality can defer
    to the cheap key comparison.
    """
    if isinstance(a, StarlarkList) and isinstance(b, StarlarkList):
        if len(a) != len(b):
            return False
        for x, y in zip(a._data, b._data, strict=True):
            if not equal(x, y, _depth):
                return False
        return True
    if isinstance(a, Dict) and isinstance(b, Dict):
        if len(a) != len(b):
            return False
        for k, v in a._data.items():
            if k not in b._data:
                return False
            if not equal(v, b._data[k], _depth):
                return False
        return True
    if isinstance(a, StarlarkSet) and isinstance(b, StarlarkSet):
        return a._data.keys() == b._data.keys()
    # Mismatched container types (e.g. list vs dict) are never equal.
    return False


def equal(a: Any, b: Any, _depth: int = 0) -> bool:
    """Starlark equality. Same-type structural; cross-numeric (int <-> float).

    Distinct types compare unequal. The bool/int special case follows the
    Java reference (which inherits Java's `Boolean.equals(Integer)` returning
    false), so `True == 1` is False in Starlark — matching the spec.

    Cycles between mutable values are handled by recording each pair we're
    currently comparing; a recurrence is treated as equal at that level.
    `_depth` additionally bounds linear-deep (non-cyclic) structures.
    """
    _check_compare_depth(_depth)
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
            return _equal_containers(a, b, _depth + 1)
        finally:
            seen.discard(pair)
    if type(a) is type(b):
        # NaN compares equal to itself in Starlark (identity-based equality
        # for floats), unlike Python's IEEE-754 default.
        if isinstance(a, float) and a != a and isinstance(b, float) and b != b:
            return True
        if isinstance(a, tuple):
            if len(a) != len(b):
                return False
            for x, y in zip(a, b, strict=True):
                if not equal(x, y, _depth + 1):
                    return False
            return True
        return a == b
    # bool/int cross: spec says distinct — explicitly check before int/float.
    if isinstance(a, bool) or isinstance(b, bool):
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return False


def less_than(a: Any, b: Any, _depth: int = 0) -> bool:
    """Starlark `<`. Same-type ordered; numeric int <-> float allowed.

    NaN sorts greater than every non-NaN value (matching Java's Double.compare).
    `_depth` bounds structural recursion through nested lists/tuples.
    """
    _check_compare_depth(_depth)
    if isinstance(a, bool) and isinstance(b, bool):
        return (not a) and b
    # Reject bool vs non-bool numeric per the spec.
    if isinstance(a, bool) or isinstance(b, bool):
        raise EvalError(f"unsupported comparison: {starlark_type(a)} <=> {starlark_type(b)}")
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
        for x, y in zip(a, b, strict=False):
            if not equal(x, y, _depth + 1):
                return less_than(x, y, _depth + 1)
        return len(a) < len(b)
    if isinstance(a, StarlarkList) and isinstance(b, StarlarkList):
        for x, y in zip(a, b, strict=False):
            if not equal(x, y, _depth + 1):
                return less_than(x, y, _depth + 1)
        return len(a) < len(b)
    # Preserve operand order so `min(string, int)` differs from
    # `min(int, string)` in the error message; the spec uses `<=>` to indicate
    # this is a generic ordered-comparison error, not specifically `<`.
    raise EvalError(f"unsupported comparison: {starlark_type(a)} <=> {starlark_type(b)}")


# --------------------------------------------------------------- repr


def _int_to_str(value: int) -> str:
    """Decimal stringification of an int, with the CPython digit cap normalized.

    CPython caps decimal int<->str conversions at `sys.int_max_str_digits`
    (default 4300) to bound a quadratic algorithm; converting a larger int
    leaks a raw `ValueError`. We never raise `sys.set_int_max_str_digits`
    globally — that would reintroduce the DoS — so an int can be valid under
    our own magnitude cap yet not default-stringifiable. Convert that
    `ValueError` into a clean `EvalError`. (Hex/oct/bin are not digit-capped,
    so the `%x`/`%o` format paths don't need this.)
    """
    try:
        return str(value)
    except ValueError:
        raise EvalError("integer too large to convert to string") from None


def repr_starlark(value: Any, _seen: set | None = None, _depth: int = 0) -> str:
    """Returns the canonical Starlark representation of a value (`repr(x)`)."""
    if _seen is None:
        _seen = set()
    # Defuse stack overflow on deeply nested non-cyclic structures (e.g.,
    # `x = []` then `for i in range(N): x = [x]`). The cycle-detection set
    # already handles cyclic references; this catches the linear-deep case.
    from .limits import MAX_NESTING_DEPTH

    if _depth > MAX_NESTING_DEPTH:
        from .errors import EvalError as _EE

        raise _EE(f"value too deeply nested for repr (>{MAX_NESTING_DEPTH} levels)")
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
        return _int_to_str(value)
    if isinstance(value, float):
        return _float_repr(value)
    if isinstance(value, str):
        return _str_repr(value)
    if isinstance(value, tuple):
        if len(value) == 1:
            return f"({repr_starlark(value[0], _seen, _depth + 1)},)"
        return "(" + ", ".join(repr_starlark(x, _seen, _depth + 1) for x in value) + ")"
    if isinstance(value, StarlarkList):
        return "[" + ", ".join(repr_starlark(x, _seen, _depth + 1) for x in value) + "]"
    if isinstance(value, Dict):
        return (
            "{"
            + ", ".join(
                f"{repr_starlark(k, _seen, _depth + 1)}: {repr_starlark(v, _seen, _depth + 1)}"
                for k, v in value.items()
            )
            + "}"
        )
    if isinstance(value, StarlarkSet):
        if len(value) == 0:
            return "set()"
        return "set([" + ", ".join(repr_starlark(x, _seen, _depth + 1) for x in value) + "])"
    if isinstance(value, Range):
        if value.step == 1:
            return f"range({value.start}, {value.stop})"
        return f"range({value.start}, {value.stop}, {value.step})"
    if isinstance(value, BuiltinFunction):
        return (
            f"<built-in function {value.name}>"
            if not value.self_repr
            else (f"<built-in method {value.name.split('.')[-1]} of {value.self_repr} value>")
        )
    # User-defined functions — let their __repr__ handle it.
    return repr(value)


def str_starlark(value: Any) -> str:
    """`str(x)`. Same as repr for most types, but plain text for strings."""
    if isinstance(value, str):
        return value
    return repr_starlark(value)


def _float_repr(x: float) -> str:
    """Render a float using Java/Go's repr conventions.

    The Java reference uses Double.toString, which renders absolute values in
    [10^-3, 10^7) in fixed notation and elsewhere in scientific. Python's
    repr() switches at 1e-4 / 1e16 and produces "1e+16" where Java would
    emit "10000000000000000.0". We follow Java's thresholds.
    """
    if x != x:  # NaN
        return "nan"
    if x == float("inf"):
        return "+inf"
    if x == float("-inf"):
        return "-inf"
    if x == 0.0:
        return "-0.0" if _is_neg_zero(x) else "0.0"

    # Use Python's repr as the basis (it produces the shortest round-trip
    # representation, same as Java's Double.toString). Then, if Python chose
    # scientific notation but we're in Java's "fixed range", convert to
    # fixed form.
    s = repr(x)
    if "e" in s or "E" in s:
        if 1e-3 <= abs(x) < 1e17:
            from decimal import Decimal

            d = Decimal(s)
            s = format(d, "f")
            if "." not in s:
                s += ".0"
        return s
    # Repr already in fixed form; ensure it has a decimal point.
    if "." not in s:
        s += ".0"
    return s


def _is_neg_zero(x: float) -> bool:
    import math

    return x == 0.0 and math.copysign(1.0, x) == -1.0


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
            out.append(f"\\x{ord(ch):02x}")
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
