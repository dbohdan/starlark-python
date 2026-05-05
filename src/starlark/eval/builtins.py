"""Core Starlark universal builtins.

Mirrors `net.starlark.java.eval.MethodLibrary`. Each function is wrapped in
a `BuiltinFunction` whose `impl` is a Python callable. Argument validation
is mostly inline; we keep it simple.
"""

from __future__ import annotations

from typing import Any

from .errors import EvalError
from .mutability import Mutability
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

# Builtins that need to allocate mutable values use the current Module's
# Mutability. Builtins that need to call back into Starlark (e.g.
# `sorted(key=fn)`) use the current Thread. Both are stack-pushed by the
# evaluator's `call()` and `eval_file()`.
_CURRENT_MUTABILITY: list[Mutability] = []
_CURRENT_THREAD: list[Any] = []  # actually Thread, but avoid circular import


def with_mutability(mutability: Mutability):
    class _Ctx:
        def __enter__(self):
            _CURRENT_MUTABILITY.append(mutability)
            return self

        def __exit__(self, *exc):
            _CURRENT_MUTABILITY.pop()
            return False

    return _Ctx()


def with_thread(thread: Any):
    class _Ctx:
        def __enter__(self):
            _CURRENT_THREAD.append(thread)
            return self

        def __exit__(self, *exc):
            _CURRENT_THREAD.pop()
            return False

    return _Ctx()


def _mut() -> Mutability:
    if _CURRENT_MUTABILITY:
        return _CURRENT_MUTABILITY[-1]
    return Mutability("<builtin>")


def _call_starlark(fn: Any, *args: Any) -> Any:
    """Invoke a Starlark callable from inside a builtin (e.g., `sorted` key)."""
    if isinstance(fn, BuiltinFunction):
        return fn.impl(*args)
    if not _CURRENT_THREAD:
        raise EvalError("cannot call user-defined function from this context")
    from .evaluator import call as _call
    return _call(fn, list(args), {}, _CURRENT_THREAD[-1])


def _check_callable(name: str, value: Any) -> None:
    """Raise EvalError if `value` isn't a callable (Starlark or builtin)."""
    if value is None:
        return
    from .function import StarlarkFunction
    if isinstance(value, (BuiltinFunction, StarlarkFunction)):
        return
    raise EvalError(
        f"parameter '{name}' got value of type '{starlark_type(value)}', want 'callable or NoneType'"
    )


# ---------------------------------------------------------------- helpers


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _to_iter(v: Any):
    if isinstance(v, str):
        return iter(v)
    if isinstance(v, (tuple, StarlarkList, Dict, StarlarkSet, Range)):
        return iter(v)
    raise EvalError(f"got value of type '{starlark_type(v)}', want 'iterable'")


# ---------------------------------------------------------------- type / len


def b_type(x: Any) -> str:
    return starlark_type(x)


def b_len(x: Any) -> int:
    if isinstance(x, str):
        return len(x)
    if isinstance(x, (tuple, StarlarkList, Dict, StarlarkSet, Range)):
        return len(x)
    raise EvalError(f"{starlark_type(x)} object has no len()")


def b_bool(x: Any = False) -> bool:
    return truth(x)


def b_repr(x: Any) -> str:
    return repr_starlark(x)


def b_str(x: Any = "") -> str:
    return str_starlark(x)


def b_print(*args, sep: str = " ", end: str = "") -> None:
    """`print` writes to stderr in the Java reference; we use stdout here.

    Print currently has no side-channel; the evaluator can override.
    """
    text = sep.join(str_starlark(a) for a in args)
    if end:
        text += end
    print(text)


def b_fail(*args, sep: str = " ") -> None:
    msg = sep.join(str_starlark(a) for a in args)
    raise EvalError(msg)


# ---------------------------------------------------------------- numbers


def b_int(x: Any = 0, base: Any = None) -> int:
    if base is not None:
        if not isinstance(x, str):
            raise EvalError("int() base parameter requires a string argument")
        if not _is_int(base):
            raise EvalError("int() base must be int")
        try:
            return int(x.strip(), base)
        except ValueError:
            raise EvalError(f"invalid literal for int() with base {base}: {x!r}") from None
    if isinstance(x, bool):
        return 1 if x else 0
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        if x != x or x == float("inf") or x == float("-inf"):
            raise EvalError(f"int() argument is not a finite number: {x}")
        return int(x)
    if isinstance(x, str):
        s = x.strip()
        sign = ""
        body = s
        if body[:1] in ("+", "-"):
            sign = body[0]
            body = body[1:]
        try:
            if body.startswith(("0x", "0X")):
                return int(sign + body[2:], 16)
            if body.startswith(("0o", "0O")):
                return int(sign + body[2:], 8)
            if body.startswith(("0b", "0B")):
                return int(sign + body[2:], 2)
            return int(s)
        except ValueError:
            raise EvalError(f"int() invalid literal: {x!r}") from None
    raise EvalError(f"int() does not accept {starlark_type(x)}")


def b_float(x: Any = 0.0) -> float:
    if isinstance(x, bool):
        return 1.0 if x else 0.0
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.strip().lower()
        if s in ("inf", "+inf", "infinity", "+infinity"):
            return float("inf")
        if s in ("-inf", "-infinity"):
            return float("-inf")
        if s in ("nan", "+nan", "-nan"):
            return float("nan")
        try:
            return float(x)
        except ValueError:
            raise EvalError(f"float() invalid literal: {x!r}") from None
    raise EvalError(f"float() does not accept {starlark_type(x)}")


def b_abs(x: Any) -> Any:
    if isinstance(x, bool):
        raise EvalError("abs() does not accept bool")
    if isinstance(x, (int, float)):
        return abs(x)
    raise EvalError(f"abs() does not accept {starlark_type(x)}")


def b_hash(x: Any) -> int:
    if isinstance(x, str):
        # Use Python's hash but mask to a stable 32-bit-ish int.
        return hash(x) & 0xFFFFFFFF
    if isinstance(x, (int, bool, float, type(None))):
        return hash(x) & 0xFFFFFFFF
    if isinstance(x, tuple):
        check_hashable(x)
        return hash(x) & 0xFFFFFFFF
    raise EvalError(f"unhashable type: {starlark_type(x)!r}")


# ---------------------------------------------------------------- collections


def b_list(x: Any = ()) -> StarlarkList:
    return StarlarkList(list(_to_iter(x)) if x != () else [], _mut())


def b_tuple(x: Any = ()) -> tuple:
    if x == ():
        return ()
    return tuple(_to_iter(x))


def b_dict(*args, **kwargs) -> Dict:
    if len(args) > 1:
        raise EvalError("dict() takes at most 1 positional argument")
    d = Dict(mutability=_mut())
    if args:
        a = args[0]
        if isinstance(a, Dict):
            for k, v in a.items():
                d[k] = v
        elif isinstance(a, dict):
            for k, v in a.items():
                check_hashable(k)
                d[k] = v
        else:
            for pair in _to_iter(a):
                items = list(_to_iter(pair))
                if len(items) != 2:
                    raise EvalError("dict() pair must have exactly 2 elements")
                check_hashable(items[0])
                d[items[0]] = items[1]
    for k, v in kwargs.items():
        d[k] = v
    return d


def b_set(x: Any = ()) -> StarlarkSet:
    if x == ():
        return StarlarkSet(mutability=_mut())
    return StarlarkSet(list(_to_iter(x)), _mut())


def b_range(*args) -> Range:
    if not 1 <= len(args) <= 3:
        raise EvalError(f"range expected 1 to 3 arguments, got {len(args)}")
    for a in args:
        if not _is_int(a):
            raise EvalError("range() requires int arguments")
    if len(args) == 1:
        return Range(0, args[0], 1)
    if len(args) == 2:
        return Range(args[0], args[1], 1)
    return Range(args[0], args[1], args[2])


def b_enumerate(x: Any, start: int = 0) -> StarlarkList:
    if not _is_int(start):
        raise EvalError("enumerate() start must be int")
    return StarlarkList(
        [(i + start, v) for i, v in enumerate(_to_iter(x))], _mut()
    )


def b_zip(*args) -> StarlarkList:
    iters = [list(_to_iter(a)) for a in args]
    return StarlarkList([tuple(t) for t in zip(*iters, strict=False)], _mut())


def b_reversed(x: Any) -> StarlarkList:
    return StarlarkList(list(reversed(list(_to_iter(x)))), _mut())


def b_sorted(x: Any, *, key: Any = None, reverse: bool = False) -> StarlarkList:
    _check_callable("key", key)
    items = list(_to_iter(x))
    keys = [_call_starlark(key, v) if key is not None else v for v in items]

    class _K:
        __slots__ = ("i", "k")

        def __init__(self, k: Any, i: int) -> None:
            self.k = k
            self.i = i

        def __lt__(self, other: _K) -> bool:
            if equal(self.k, other.k):
                return self.i < other.i
            return less_than(self.k, other.k)

    indexed = sorted(range(len(items)), key=lambda i: _K(keys[i], i))
    out = [items[i] for i in indexed]
    if reverse:
        out.reverse()
    return StarlarkList(out, _mut())


def b_min(*args, key: Any = None) -> Any:
    return _min_max(args, key, _is_min=True)


def b_max(*args, key: Any = None) -> Any:
    return _min_max(args, key, _is_min=False)


def _min_max(args, key, *, _is_min: bool) -> Any:
    _check_callable("key", key)
    if len(args) == 0:
        raise EvalError("expected at least one item")
    if len(args) == 1:
        # Single-arg case: iterate.
        try:
            it = _to_iter(args[0])
        except EvalError:
            raise EvalError(
                f"type '{starlark_type(args[0])}' is not iterable"
            ) from None
        items = list(it)
        if not items:
            raise EvalError("expected at least one item")
    else:
        items = list(args)
    best = items[0]
    best_key = _call_starlark(key, best) if key is not None else best
    for v in items[1:]:
        vk = _call_starlark(key, v) if key is not None else v
        better = less_than(vk, best_key) if _is_min else less_than(best_key, vk)
        if better:
            best, best_key = v, vk
    return best


def b_all(x: Any) -> bool:
    for v in _to_iter(x):
        if not truth(v):
            return False
    return True


def b_any(x: Any) -> bool:
    for v in _to_iter(x):
        if truth(v):
            return True
    return False


def b_sum(x: Any, start: Any = 0) -> Any:
    total = start
    for v in _to_iter(x):
        total = total + v
    return total


# ---------------------------------------------------------------- attr / dir


def b_hasattr(obj: Any, name: Any) -> bool:
    if not isinstance(name, str):
        raise EvalError(
            f"parameter 'name' got value of type '{starlark_type(name)}', want 'string'"
        )
    fields = getattr(obj, "fields", None)
    if isinstance(fields, dict) and name in fields:
        return True
    from .methods import get_method
    return get_method(obj, name) is not None


def b_getattr(obj: Any, name: Any, *defaults) -> Any:
    if not isinstance(name, str):
        raise EvalError(
            f"parameter 'name' got value of type '{starlark_type(name)}', want 'string'"
        )
    fields = getattr(obj, "fields", None)
    if isinstance(fields, dict) and name in fields:
        return fields[name]
    from .methods import get_method
    m = get_method(obj, name)
    if m is not None:
        return m
    if defaults:
        return defaults[0]
    raise EvalError(f"'{starlark_type(obj)}' value has no field or method '{name}'")


def b_dir(obj: Any) -> StarlarkList:
    from .methods import _DICT_METHODS, _LIST_METHODS, _SET_METHODS, _STRING_METHODS
    names: list[str] = []
    if isinstance(obj, str):
        names = sorted(_STRING_METHODS.keys())
    elif isinstance(obj, StarlarkList):
        names = sorted(_LIST_METHODS.keys())
    elif isinstance(obj, Dict):
        names = sorted(_DICT_METHODS.keys())
    elif isinstance(obj, StarlarkSet):
        names = sorted(_SET_METHODS.keys())
    fields = getattr(obj, "fields", None)
    if isinstance(fields, dict):
        names = sorted(set(names) | set(fields.keys()))
    return StarlarkList(names, _mut())


# ---------------------------------------------------------------- registry


def make_universal() -> dict[str, Any]:
    """Returns the universal namespace as a dict suitable for `Thread.universal`."""
    table: dict[str, Any] = {
        "None": None,
        "True": True,
        "False": False,
    }
    pairs: list[tuple[str, Any]] = [
        ("len", b_len),
        ("type", b_type),
        ("bool", b_bool),
        ("repr", b_repr),
        ("str", b_str),
        ("int", b_int),
        ("float", b_float),
        ("abs", b_abs),
        ("hash", b_hash),
        ("list", b_list),
        ("tuple", b_tuple),
        ("dict", b_dict),
        ("set", b_set),
        ("range", b_range),
        ("enumerate", b_enumerate),
        ("zip", b_zip),
        ("reversed", b_reversed),
        ("sorted", b_sorted),
        ("min", b_min),
        ("max", b_max),
        ("all", b_all),
        ("any", b_any),
        ("sum", b_sum),
        ("hasattr", b_hasattr),
        ("getattr", b_getattr),
        ("dir", b_dir),
        ("print", b_print),
        ("fail", b_fail),
    ]
    for name, fn in pairs:
        table[name] = BuiltinFunction(name=name, impl=fn)
    from .json_module import make_module
    table["json"] = make_module()
    return table


__all__ = ["make_universal", "with_mutability"]
