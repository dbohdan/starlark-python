"""String methods, exposed via the per-type method table.

Mirrors `net.starlark.java.eval.StringModule`. Most methods are thin
wrappers over Python's str methods. We re-implement the substring search
helpers to use code-point indexing (per the spec — see README divergence).
"""

from __future__ import annotations

from typing import Any

from .errors import EvalError
from .methods import register_string_method
from .values import StarlarkList
from .values import starlark_type as _st


def _resolve_indices(s: str, start, end) -> tuple[int, int]:
    n = len(s)
    if start is None:
        start = 0
    if end is None:
        end = n
    if not isinstance(start, int) or isinstance(start, bool):
        raise EvalError("start must be an int")
    if not isinstance(end, int) or isinstance(end, bool):
        raise EvalError("end must be an int")
    if start < 0:
        start = max(0, n + start)
    if end < 0:
        end = max(0, n + end)
    return min(start, n), min(end, n)


# ---------------------------------------------------------------- starts/ends


def s_startswith(s: str, prefix: Any, start: Any = None, end: Any = None) -> bool:
    a, b = _resolve_indices(s, start, end)
    sub = s[a:b]
    if isinstance(prefix, tuple):
        for i, p in enumerate(prefix):
            if not isinstance(p, str):
                raise EvalError(
                    f"at index {i} of sub, got element of type {_st(p)}, want string"
                )
        return any(sub.startswith(p) for p in prefix)
    if not isinstance(prefix, str):
        raise EvalError(
            f"got value of type '{_st(prefix)}', want 'string or tuple'"
        )
    return sub.startswith(prefix)


def s_endswith(s: str, suffix: Any, start: Any = None, end: Any = None) -> bool:
    a, b = _resolve_indices(s, start, end)
    sub = s[a:b]
    if isinstance(suffix, tuple):
        for i, p in enumerate(suffix):
            if not isinstance(p, str):
                raise EvalError(
                    f"at index {i} of sub, got element of type {_st(p)}, want string"
                )
        return any(sub.endswith(p) for p in suffix)
    if not isinstance(suffix, str):
        raise EvalError(
            f"got value of type '{_st(suffix)}', want 'string or tuple'"
        )
    return sub.endswith(suffix)


# ---------------------------------------------------------------- find / index


def s_find(s: str, sub: str, start: Any = None, end: Any = None) -> int:
    if not isinstance(sub, str):
        raise EvalError("find() requires a string")
    a, b = _resolve_indices(s, start, end)
    idx = s[a:b].find(sub)
    return idx + a if idx >= 0 else -1


def s_rfind(s: str, sub: str, start: Any = None, end: Any = None) -> int:
    if not isinstance(sub, str):
        raise EvalError("rfind() requires a string")
    a, b = _resolve_indices(s, start, end)
    idx = s[a:b].rfind(sub)
    return idx + a if idx >= 0 else -1


def s_index(s: str, sub: str, start: Any = None, end: Any = None) -> int:
    idx = s_find(s, sub, start, end)
    if idx < 0:
        raise EvalError("substring not found")
    return idx


def s_rindex(s: str, sub: str, start: Any = None, end: Any = None) -> int:
    idx = s_rfind(s, sub, start, end)
    if idx < 0:
        raise EvalError("substring not found")
    return idx


def s_count(s: str, sub: str, start: Any = None, end: Any = None) -> int:
    if not isinstance(sub, str):
        raise EvalError("count() requires a string")
    a, b = _resolve_indices(s, start, end)
    return s[a:b].count(sub)


# ---------------------------------------------------------------- case


def s_lower(s: str) -> str:
    return s.lower()


def s_upper(s: str) -> str:
    return s.upper()


def s_capitalize(s: str) -> str:
    return s.capitalize()


def s_title(s: str) -> str:
    # Python's title differs slightly from Starlark spec; here we follow
    # Starlark / Bazel: a letter is title-cased iff the previous char is
    # not a letter.
    out = []
    prev_letter = False
    for ch in s:
        if ch.isalpha():
            out.append(ch.upper() if not prev_letter else ch.lower())
            prev_letter = True
        else:
            out.append(ch)
            prev_letter = False
    return "".join(out)


# ---------------------------------------------------------------- strip


def _strip_chars(spec: Any) -> str | None:
    if spec is None:
        return None
    if not isinstance(spec, str):
        raise EvalError("strip-chars argument must be a string")
    return spec


def s_strip(s: str, chars: Any = None) -> str:
    return s.strip(_strip_chars(chars))


def s_lstrip(s: str, chars: Any = None) -> str:
    return s.lstrip(_strip_chars(chars))


def s_rstrip(s: str, chars: Any = None) -> str:
    return s.rstrip(_strip_chars(chars))


# ---------------------------------------------------------------- split


def s_split(s: str, sep: Any = None, maxsplit: Any = None) -> StarlarkList:
    from .builtins import _mut
    if sep is not None:
        if not isinstance(sep, str):
            raise EvalError(f"got value of type '{type(sep).__name__}', want 'string or None'")
        if not sep:
            raise EvalError("Empty separator")
    parts = s.split(sep, -1 if maxsplit is None else maxsplit)
    return StarlarkList(parts, _mut())


def s_rsplit(s: str, sep: Any = None, maxsplit: Any = None) -> StarlarkList:
    from .builtins import _mut
    if sep is not None:
        if not isinstance(sep, str):
            raise EvalError(f"got value of type '{type(sep).__name__}', want 'string or None'")
        if not sep:
            raise EvalError("Empty separator")
    parts = s.rsplit(sep, -1 if maxsplit is None else maxsplit)
    return StarlarkList(parts, _mut())


def s_splitlines(s: str, keepends: bool = False) -> StarlarkList:
    from .builtins import _mut
    return StarlarkList(s.splitlines(keepends), _mut())


def s_partition(s: str, sep: str) -> tuple:
    if not isinstance(sep, str):
        raise EvalError(
            f"got value of type '{type(sep).__name__}', want 'string'"
        )
    if not sep:
        raise EvalError("empty separator")
    return s.partition(sep)


def s_rpartition(s: str, sep: str) -> tuple:
    if not isinstance(sep, str):
        raise EvalError(
            f"got value of type '{type(sep).__name__}', want 'string'"
        )
    if not sep:
        raise EvalError("empty separator")
    return s.rpartition(sep)


# ---------------------------------------------------------------- join / replace


def s_join(s: str, iterable: Any) -> str:
    parts: list[str] = []
    from .values import starlark_type
    for x in iterable:
        if not isinstance(x, str):
            raise EvalError(
                f"join() requires a sequence of strings (got {starlark_type(x)})"
            )
        parts.append(x)
    return s.join(parts)


def s_replace(s: str, old: str, new: str, count: Any = None) -> str:
    if not isinstance(old, str) or not isinstance(new, str):
        raise EvalError("replace() requires string arguments")
    if count is None:
        return s.replace(old, new)
    if not isinstance(count, int) or isinstance(count, bool):
        raise EvalError("replace() count must be an int")
    return s.replace(old, new, count)


def s_removeprefix(s: str, prefix: str) -> str:
    if not isinstance(prefix, str):
        raise EvalError("removeprefix() requires a string")
    return s[len(prefix):] if s.startswith(prefix) else s


def s_removesuffix(s: str, suffix: str) -> str:
    if not isinstance(suffix, str):
        raise EvalError("removesuffix() requires a string")
    return s[:-len(suffix)] if suffix and s.endswith(suffix) else s


# ---------------------------------------------------------------- predicate


def _all_chars(s: str, pred) -> bool:
    return len(s) > 0 and all(pred(c) for c in s)


def s_isalpha(s: str) -> bool:
    return _all_chars(s, str.isalpha)


def s_isalnum(s: str) -> bool:
    return _all_chars(s, str.isalnum)


def s_isdigit(s: str) -> bool:
    return _all_chars(s, str.isdigit)


def s_isspace(s: str) -> bool:
    return _all_chars(s, str.isspace)


def s_islower(s: str) -> bool:
    has_cased = any(c.isalpha() for c in s)
    return has_cased and all((not c.isalpha()) or c.islower() for c in s)


def s_isupper(s: str) -> bool:
    has_cased = any(c.isalpha() for c in s)
    return has_cased and all((not c.isalpha()) or c.isupper() for c in s)


def s_istitle(s: str) -> bool:
    return s.istitle()


# ---------------------------------------------------------------- elems


def s_elems(s: str) -> StarlarkList:
    from .builtins import _mut
    return StarlarkList(list(s), _mut())


# ---------------------------------------------------------------- format


def s_format(s: str, *args, **kwargs) -> str:
    """`"hello {0}".format("world")`. Supports {pos}, {name}, {} positional."""
    return _format_impl(s, args, kwargs)


def _format_impl(template: str, args: tuple, kwargs: dict) -> str:
    out: list[str] = []
    i = 0
    n = len(template)
    auto_index = 0
    while i < n:
        c = template[i]
        if c == "{":
            if i + 1 < n and template[i + 1] == "{":
                out.append("{")
                i += 2
                continue
            j = template.find("}", i)
            if j < 0:
                raise EvalError("missing '}' in format string")
            spec = template[i + 1 : j]
            i = j + 1
            # Convert specifier (no !s/!r/:fmt for simplicity).
            # Split spec into name and conversion.
            conv = ""
            if "!" in spec:
                spec, conv = spec.rsplit("!", 1)
            # Look up the value.
            if spec == "":
                if auto_index >= len(args):
                    raise EvalError("not enough positional arguments for format")
                value = args[auto_index]
                auto_index += 1
            elif spec.isdigit():
                idx = int(spec)
                if idx >= len(args):
                    raise EvalError(f"index {idx} out of range for format args")
                value = args[idx]
            else:
                if spec not in kwargs:
                    raise EvalError(f"missing keyword argument: {spec}")
                value = kwargs[spec]
            from .values import repr_starlark, str_starlark
            if conv == "r":
                out.append(repr_starlark(value))
            else:
                out.append(str_starlark(value))
        elif c == "}":
            if i + 1 < n and template[i + 1] == "}":
                out.append("}")
                i += 2
                continue
            raise EvalError("single '}' in format string")
        else:
            out.append(c)
            i += 1
    return "".join(out)


# ---------------------------------------------------------------- registration


def register_all() -> None:
    pairs: list[tuple[str, Any]] = [
        ("startswith", s_startswith),
        ("endswith", s_endswith),
        ("find", s_find),
        ("rfind", s_rfind),
        ("index", s_index),
        ("rindex", s_rindex),
        ("count", s_count),
        ("lower", s_lower),
        ("upper", s_upper),
        ("capitalize", s_capitalize),
        ("title", s_title),
        ("strip", s_strip),
        ("lstrip", s_lstrip),
        ("rstrip", s_rstrip),
        ("split", s_split),
        ("rsplit", s_rsplit),
        ("splitlines", s_splitlines),
        ("partition", s_partition),
        ("rpartition", s_rpartition),
        ("join", s_join),
        ("replace", s_replace),
        ("removeprefix", s_removeprefix),
        ("removesuffix", s_removesuffix),
        ("isalpha", s_isalpha),
        ("isalnum", s_isalnum),
        ("isdigit", s_isdigit),
        ("isspace", s_isspace),
        ("islower", s_islower),
        ("isupper", s_isupper),
        ("istitle", s_istitle),
        ("elems", s_elems),
        ("format", s_format),
    ]
    for name, fn in pairs:
        register_string_method(name, fn)


# Register on import.
register_all()


__all__ = ["register_all"]
