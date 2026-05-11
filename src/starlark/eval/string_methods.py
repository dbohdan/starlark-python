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
                raise EvalError(f"at index {i} of sub, got element of type {_st(p)}, want string")
        return any(sub.startswith(p) for p in prefix)
    if not isinstance(prefix, str):
        raise EvalError(f"got value of type '{_st(prefix)}', want 'string or tuple'")
    return sub.startswith(prefix)


def s_endswith(s: str, suffix: Any, start: Any = None, end: Any = None) -> bool:
    a, b = _resolve_indices(s, start, end)
    sub = s[a:b]
    if isinstance(suffix, tuple):
        for i, p in enumerate(suffix):
            if not isinstance(p, str):
                raise EvalError(f"at index {i} of sub, got element of type {_st(p)}, want string")
        return any(sub.endswith(p) for p in suffix)
    if not isinstance(suffix, str):
        raise EvalError(f"got value of type '{_st(suffix)}', want 'string or tuple'")
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
        raise EvalError(f"got value of type '{type(sep).__name__}', want 'string'")
    if not sep:
        raise EvalError("empty separator")
    return s.partition(sep)


def s_rpartition(s: str, sep: str) -> tuple:
    if not isinstance(sep, str):
        raise EvalError(f"got value of type '{type(sep).__name__}', want 'string'")
    if not sep:
        raise EvalError("empty separator")
    return s.rpartition(sep)


# ---------------------------------------------------------------- join / replace


def s_join(s: str, iterable: Any) -> str:
    parts: list[str] = []
    from .values import starlark_type

    for x in iterable:
        if not isinstance(x, str):
            raise EvalError(f"join() requires a sequence of strings (got {starlark_type(x)})")
        parts.append(x)
    return s.join(parts)


def s_replace(s: str, old: Any, new: Any, count: Any = -1) -> str:
    if not isinstance(old, str):
        raise EvalError(f"got value of type '{_st(old)}' for 'old', want 'string'")
    if not isinstance(new, str):
        raise EvalError(f"got value of type '{_st(new)}' for 'new', want 'string'")
    # count is required to be an int. Bazel rejects None explicitly even though
    # -1 is the documented default.
    if not isinstance(count, int) or isinstance(count, bool):
        raise EvalError(f"parameter 'count' got value of type '{_st(count)}', want 'int'")
    return s.replace(old, new, count)


def s_removeprefix(s: str, prefix: Any) -> str:
    if not isinstance(prefix, str):
        raise EvalError(f"got value of type '{_st(prefix)}', want 'string'")
    return s[len(prefix) :] if s.startswith(prefix) else s


def s_removesuffix(s: str, suffix: Any) -> str:
    if not isinstance(suffix, str):
        raise EvalError(f"got value of type '{_st(suffix)}', want 'string'")
    return s[: -len(suffix)] if suffix and s.endswith(suffix) else s


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


# ---------------------------------------------------------------- elems / elem_ords / codepoints / codepoint_ords


def s_elems(s: str) -> StarlarkList:
    from .builtins import _mut

    return StarlarkList(list(s), _mut())


def s_elem_ords(s: str) -> StarlarkList:
    """Return the UTF-8 byte values of the string as a list of ints."""
    from .builtins import _mut

    return StarlarkList(list(s.encode("utf-8")), _mut())


def s_codepoints(s: str) -> StarlarkList:
    """Return the string split into single-code-point substrings."""
    from .builtins import _mut

    return StarlarkList(list(s), _mut())


def s_codepoint_ords(s: str) -> StarlarkList:
    """Return the integer Unicode code points of the string."""
    from .builtins import _mut

    return StarlarkList([ord(c) for c in s], _mut())


# ---------------------------------------------------------------- format


def s_format(s: str, *args, **kwargs) -> str:
    """`"hello {0}".format("world")`. Supports {pos}, {name}, {} positional."""
    return _format_impl(s, args, kwargs)


def _format_impl(template: str, args: tuple, kwargs: dict) -> str:
    """str.format implementation matching the spec.

    Field name grammar: digits OR a Python identifier. Anything else inside
    the braces (`,`, `.`, `[`, `]`, `(`, `)`, `:`, etc.) is rejected with an
    "Invalid character X inside replacement field" error. The `:` format
    spec from PEP 3101 is *not* supported (Starlark spec doesn't include it).
    """
    from .values import repr_starlark, str_starlark

    out: list[str] = []
    i = 0
    n = len(template)
    # Track whether positional fields have used the implicit (`{}`) form or
    # the explicit (`{0}`) form. Mixing is rejected.
    seen_implicit = False
    seen_explicit_positional = False
    auto_index = 0

    while i < n:
        c = template[i]
        if c == "{":
            # `{{` -> literal `{`.
            if i + 1 < n and template[i + 1] == "{":
                out.append("{")
                i += 2
                continue
            # Find the matching `}`. Reject nested `{`.
            j = i + 1
            while j < n and template[j] != "}":
                if template[j] == "{":
                    raise EvalError("Nested replacement fields are not supported")
                j += 1
            if j >= n:
                raise EvalError("unmatched '{' in format string")
            spec = template[i + 1 : j]
            i = j + 1

            # Split off optional `!r` / `!s` conversion.
            conv = ""
            if "!" in spec:
                spec, conv = spec.split("!", 1)
                if conv not in ("r", "s"):
                    raise EvalError(f"unknown conversion: !{conv}")

            # Validate the field name.
            if spec == "":
                # Implicit positional `{}`.
                if seen_explicit_positional:
                    raise EvalError(
                        "Cannot mix manual and automatic numbering of positional fields"
                    )
                seen_implicit = True
                if auto_index >= len(args):
                    raise EvalError(f"No replacement found for index {auto_index}")
                value = args[auto_index]
                auto_index += 1
            elif _looks_like_int_field(spec):
                # Explicit positional `{N}` (possibly `{-N}`).
                if seen_implicit:
                    raise EvalError(
                        "Cannot mix manual and automatic numbering of positional fields"
                    )
                seen_explicit_positional = True
                idx = int(spec)
                if idx < 0 or idx >= len(args):
                    raise EvalError(f"No replacement found for index {idx}")
                value = args[idx]
            else:
                # Keyword field. The name must be a valid Starlark identifier
                # (letters, digits, underscore — no dots, brackets, commas,
                # parentheses, etc.). Bazel's spec rejects them with
                # "Invalid character X inside replacement field".
                _validate_keyword_field(spec)
                if spec not in kwargs:
                    raise EvalError(f"Missing argument {spec!r}")
                value = kwargs[spec]

            if conv == "r":
                out.append(repr_starlark(value))
            else:
                out.append(str_starlark(value))
        elif c == "}":
            # `}}` -> literal `}`.
            if i + 1 < n and template[i + 1] == "}":
                out.append("}")
                i += 2
                continue
            raise EvalError("Found '}' without matching '{'")
        else:
            out.append(c)
            i += 1
    return "".join(out)


_FORBIDDEN_FIELD_CHARS = frozenset(",.[]")


def _looks_like_int_field(name: str) -> bool:
    """True if `name` is `[-]digits+` — a positional-index field."""
    if not name:
        return False
    if name[0] == "-":
        return len(name) > 1 and name[1:].isdigit()
    return name.isdigit()


def _validate_keyword_field(name: str) -> None:
    """Reject a replacement-field name with reserved format-spec metacharacters.

    Bazel's spec accepts most characters in keyword fields — the only ones
    rejected are `,`, `.`, `[`, `]`, which are reserved for PEP-3101-style
    field-spec sub-syntax that Starlark doesn't implement.
    """
    for ch in name:
        if ch in _FORBIDDEN_FIELD_CHARS:
            raise EvalError(f"Invalid character {ch!r} inside replacement field")


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
        ("elem_ords", s_elem_ords),
        ("codepoints", s_codepoints),
        ("codepoint_ords", s_codepoint_ords),
        ("format", s_format),
    ]
    for name, fn in pairs:
        register_string_method(name, fn)


# Register on import.
register_all()


__all__ = ["register_all"]
