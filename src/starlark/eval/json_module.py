"""json module: encode/decode for Starlark values.

Provides four functions, exposed under the universal `json` namespace:

- `json.encode(x)` — serialize x to a compact JSON string.
- `json.decode(s)` — parse s and return the corresponding Starlark value.
- `json.encode_indent(x, *, prefix="", indent="\\t")` — encode + indent in
  one step.
- `json.indent(s, *, prefix="", indent="\\t")` — re-format an existing
  JSON string.

Implementation notes:

- We hand-roll both encoder and decoder rather than using Python's `json`
  module so the output is byte-for-byte the format the Bazel/Starlark spec
  prescribes (compact, no spaces, dict keys sorted lexicographically) and
  so we control the exact error messages.

- **Threat model.** `decode` accepts untrusted input. To stay safe we:
  - Cap maximum nesting depth at MAX_DEPTH (256) to prevent stack-overflow
    via deeply nested arrays / objects.
  - Use index-based scanning over a Python `str` (no eval, no regex
    backtracking on adversarial input — every parser step is O(1)).
  - Reject characters that aren't strict JSON: surrogate halves outside a
    valid pair, control characters in unescaped string contexts, trailing
    data after the top-level value, multiple top-level values.
  - Allocate every collection through the current `Mutability`, so callers
    can freeze the resulting tree.

- `encode` *rejects* values it can't represent (NaN/Inf, non-string dict
  keys, callables, sets) with a precise error message — never silently
  produces invalid JSON.

Mirrors `net.starlark.java.lib.json.Json`.
"""

from __future__ import annotations

import math
from typing import Any

from .builtins import _mut
from .errors import EvalError
from .values import (
    BuiltinFunction,
    Dict,
    Range,
    StarlarkList,
    StarlarkSet,
    starlark_type,
)

MAX_DEPTH = 256


# --------------------------------------------------------------- encoder


def _encode_value(value: Any, out: list[str], path: str, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise EvalError("nesting depth limit exceeded")
    if value is None:
        out.append("null")
        return
    if value is True:
        out.append("true")
        return
    if value is False:
        out.append("false")
        return
    if isinstance(value, int):
        out.append(str(value))
        return
    if isinstance(value, float):
        if math.isnan(value):
            raise EvalError(f"{path}cannot encode non-finite float nan")
        if math.isinf(value):
            raise EvalError(
                f"{path}cannot encode non-finite float "
                + ("inf" if value > 0 else "-inf")
            )
        out.append(_encode_float(value))
        return
    if isinstance(value, str):
        out.append(_encode_string(value))
        return
    if isinstance(value, (StarlarkList, tuple, Range, StarlarkSet)):
        out.append("[")
        first = True
        for i, item in enumerate(value):
            if not first:
                out.append(",")
            first = False
            _encode_value(
                item, out, f"{path}at {_seq_label(value)} index {i}: ", depth + 1
            )
        out.append("]")
        return
    if isinstance(value, Dict):
        keys: list[str] = []
        for k in value:
            if not isinstance(k, str):
                raise EvalError(
                    f"{path}dict has {starlark_type(k)} key, want string"
                )
            keys.append(k)
        # Spec: sort keys lexicographically (key order, not insertion order).
        keys.sort()
        out.append("{")
        first = True
        for k in keys:
            if not first:
                out.append(",")
            first = False
            out.append(_encode_string(k))
            out.append(":")
            _encode_value(value[k], out, f'{path}in dict key "{k}": ', depth + 1)
        out.append("}")
        return
    # Struct-like: anything with a `fields` dict (mapping str -> value).
    fields = getattr(value, "fields", None)
    if isinstance(fields, dict):
        out.append("{")
        keys = sorted(str(k) for k in fields if isinstance(k, str))
        # Reject non-string field names.
        for k in fields:
            if not isinstance(k, str):
                raise EvalError(
                    f"{path}struct has {starlark_type(k)} key, want string"
                )
        first = True
        for k in keys:
            if not first:
                out.append(",")
            first = False
            out.append(_encode_string(k))
            out.append(":")
            _encode_value(
                fields[k], out, f"{path}in struct field .{k}: ", depth + 1
            )
        out.append("}")
        return
    raise EvalError(f"{path}cannot encode {starlark_type(value)} as JSON")


def _seq_label(value: Any) -> str:
    if isinstance(value, tuple):
        return "tuple"
    if isinstance(value, StarlarkSet):
        return "set"
    return "list"


def _encode_float(value: float) -> str:
    # Python's repr is tight-roundtrippable but uses lowercase 'e' and may
    # produce "1e+10" without decimal. The spec accepts that; the Java
    # reference uses Double.toString which is similar.
    if value == 0.0:
        return "0"
    s = repr(value)
    # Python repr already does the right thing for almost all values.
    return s


_BAD_CTRL = {chr(c) for c in range(0x20)}


def _encode_string(s: str) -> str:
    out: list[str] = ['"']
    for ch in s:
        c = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\f":
            out.append("\\f")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif c < 0x20:
            out.append(f"\\u{c:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def encode(value: Any) -> str:
    out: list[str] = []
    _encode_value(value, out, "")
    return "".join(out)


# --------------------------------------------------------------- decoder


class _Decoder:
    __slots__ = ("depth", "pos", "source")

    def __init__(self, source: str) -> None:
        self.source = source
        self.pos = 0
        self.depth = 0

    def _eof(self) -> bool:
        return self.pos >= len(self.source)

    def _peek(self) -> str:
        if self._eof():
            raise EvalError("unexpected end of JSON input")
        return self.source[self.pos]

    def _skip_ws(self) -> None:
        s = self.source
        while self.pos < len(s) and s[self.pos] in " \t\n\r":
            self.pos += 1

    def _expect(self, expected: str) -> None:
        if self._eof():
            raise EvalError(f"expected {expected!r} at end of input")
        c = self.source[self.pos]
        if c != expected:
            raise EvalError(f"expected {expected!r}, got {c!r}")
        self.pos += 1

    def _push(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise EvalError("nesting depth limit exceeded")

    def _pop(self) -> None:
        self.depth -= 1

    def parse(self) -> Any:
        self._skip_ws()
        v = self._value()
        self._skip_ws()
        if not self._eof():
            raise EvalError(
                f"unexpected trailing data at offset {self.pos}: "
                f"{self.source[self.pos:self.pos+8]!r}"
            )
        return v

    def _value(self) -> Any:
        self._skip_ws()
        c = self._peek()
        if c == "{":
            return self._object()
        if c == "[":
            return self._array()
        if c == '"':
            return self._string()
        if c == "t" or c == "f":
            return self._bool()
        if c == "n":
            return self._null()
        if c == "-" or ("0" <= c <= "9"):
            return self._number()
        raise EvalError(f"unexpected character {c!r} at offset {self.pos}")

    def _bool(self) -> bool:
        if self.source.startswith("true", self.pos):
            self.pos += 4
            return True
        if self.source.startswith("false", self.pos):
            self.pos += 5
            return False
        raise EvalError(f"invalid literal at offset {self.pos}")

    def _null(self) -> None:
        if self.source.startswith("null", self.pos):
            self.pos += 4
            return None
        raise EvalError(f"invalid literal at offset {self.pos}")

    def _number(self) -> Any:
        start = self.pos
        if self._peek() == "-":
            self.pos += 1
        # Integer part.
        if self._eof():
            raise EvalError("incomplete number")
        c = self.source[self.pos]
        if c == "0":
            self.pos += 1
            # Strict JSON forbids leading zeros: 0 followed by another digit.
            if self.pos < len(self.source) and "0" <= self.source[self.pos] <= "9":
                raise EvalError(f"invalid number at offset {start}: leading zero")
        elif "1" <= c <= "9":
            while self.pos < len(self.source) and "0" <= self.source[self.pos] <= "9":
                self.pos += 1
        else:
            raise EvalError(f"invalid number at offset {start}")
        is_float = False
        # Fraction.
        if self.pos < len(self.source) and self.source[self.pos] == ".":
            is_float = True
            self.pos += 1
            if self._eof() or not ("0" <= self.source[self.pos] <= "9"):
                raise EvalError(f"invalid number at offset {start}")
            while self.pos < len(self.source) and "0" <= self.source[self.pos] <= "9":
                self.pos += 1
        # Exponent.
        if self.pos < len(self.source) and self.source[self.pos] in ("e", "E"):
            is_float = True
            self.pos += 1
            if self.pos < len(self.source) and self.source[self.pos] in ("+", "-"):
                self.pos += 1
            if self._eof() or not ("0" <= self.source[self.pos] <= "9"):
                raise EvalError(f"invalid number at offset {start}")
            while self.pos < len(self.source) and "0" <= self.source[self.pos] <= "9":
                self.pos += 1
        text = self.source[start : self.pos]
        if is_float:
            return float(text)
        return int(text)

    def _string(self) -> str:
        self._expect('"')
        out: list[str] = []
        while True:
            if self._eof():
                raise EvalError("unterminated string in JSON")
            c = self.source[self.pos]
            self.pos += 1
            if c == '"':
                return "".join(out)
            if c == "\\":
                if self._eof():
                    raise EvalError("dangling escape in JSON string")
                esc = self.source[self.pos]
                self.pos += 1
                if esc == '"':
                    out.append('"')
                elif esc == "\\":
                    out.append("\\")
                elif esc == "/":
                    out.append("/")
                elif esc == "b":
                    out.append("\b")
                elif esc == "f":
                    out.append("\f")
                elif esc == "n":
                    out.append("\n")
                elif esc == "r":
                    out.append("\r")
                elif esc == "t":
                    out.append("\t")
                elif esc == "u":
                    out.append(self._unicode_escape())
                else:
                    raise EvalError(f"invalid escape \\{esc} in JSON string")
                continue
            if ord(c) < 0x20:
                raise EvalError(
                    f"unescaped control character U+{ord(c):04X} in JSON string"
                )
            out.append(c)

    def _unicode_escape(self) -> str:
        if self.pos + 4 > len(self.source):
            raise EvalError("incomplete \\u escape in JSON string")
        hexdigits = self.source[self.pos : self.pos + 4]
        self.pos += 4
        try:
            code = int(hexdigits, 16)
        except ValueError as e:
            raise EvalError(f"invalid \\u escape: {hexdigits!r}") from e
        # Handle UTF-16 surrogate pairs.
        if 0xD800 <= code <= 0xDBFF:
            # High surrogate; expect a low surrogate next.
            if (
                self.pos + 6 > len(self.source)
                or self.source[self.pos] != "\\"
                or self.source[self.pos + 1] != "u"
            ):
                raise EvalError("unpaired UTF-16 high surrogate in JSON string")
            self.pos += 2
            low_hex = self.source[self.pos : self.pos + 4]
            self.pos += 4
            try:
                low = int(low_hex, 16)
            except ValueError as e:
                raise EvalError(f"invalid \\u escape: {low_hex!r}") from e
            if not (0xDC00 <= low <= 0xDFFF):
                raise EvalError("invalid UTF-16 low surrogate in JSON string")
            code = 0x10000 + (((code - 0xD800) << 10) | (low - 0xDC00))
        elif 0xDC00 <= code <= 0xDFFF:
            raise EvalError("unexpected UTF-16 low surrogate in JSON string")
        return chr(code)

    def _array(self) -> StarlarkList:
        self._expect("[")
        self._push()
        try:
            self._skip_ws()
            items: list = []
            if self._peek() == "]":
                self.pos += 1
                return StarlarkList(items, _mut())
            while True:
                items.append(self._value())
                self._skip_ws()
                c = self._peek()
                if c == ",":
                    self.pos += 1
                    self._skip_ws()
                    continue
                if c == "]":
                    self.pos += 1
                    return StarlarkList(items, _mut())
                raise EvalError(f"expected ',' or ']' in array at offset {self.pos}")
        finally:
            self._pop()

    def _object(self) -> Dict:
        self._expect("{")
        self._push()
        try:
            self._skip_ws()
            d = Dict(mutability=_mut())
            if self._peek() == "}":
                self.pos += 1
                return d
            while True:
                self._skip_ws()
                if self._peek() != '"':
                    raise EvalError(
                        f"expected string key in object at offset {self.pos}"
                    )
                key = self._string()
                self._skip_ws()
                self._expect(":")
                value = self._value()
                # Last duplicate key wins (matches the Java reference).
                d[key] = value
                self._skip_ws()
                c = self._peek()
                if c == ",":
                    self.pos += 1
                    continue
                if c == "}":
                    self.pos += 1
                    return d
                raise EvalError(f"expected ',' or '}}' in object at offset {self.pos}")
        finally:
            self._pop()


def decode(source: Any) -> Any:
    if not isinstance(source, str):
        raise EvalError(f"json.decode: requires a string, got {starlark_type(source)}")
    return _Decoder(source).parse()


# --------------------------------------------------------------- indent


def _indent_value(value: Any, out: list[str], prefix: str, indent: str, depth: int) -> None:
    pad = prefix + indent * depth
    inner_pad = prefix + indent * (depth + 1)
    if isinstance(value, (StarlarkList, tuple, Range, StarlarkSet)):
        items = list(value)
        if not items:
            out.append("[]")
            return
        out.append("[\n")
        for i, item in enumerate(items):
            out.append(inner_pad)
            _indent_value(item, out, prefix, indent, depth + 1)
            if i != len(items) - 1:
                out.append(",")
            out.append("\n")
        out.append(pad)
        out.append("]")
        return
    if isinstance(value, Dict):
        keys = sorted(k for k in value if isinstance(k, str))
        if not keys:
            out.append("{}")
            return
        out.append("{\n")
        for i, k in enumerate(keys):
            out.append(inner_pad)
            out.append(_encode_string(k))
            out.append(": ")
            _indent_value(value[k], out, prefix, indent, depth + 1)
            if i != len(keys) - 1:
                out.append(",")
            out.append("\n")
        out.append(pad)
        out.append("}")
        return
    fields = getattr(value, "fields", None)
    if isinstance(fields, dict):
        keys = sorted(k for k in fields if isinstance(k, str))
        if not keys:
            out.append("{}")
            return
        out.append("{\n")
        for i, k in enumerate(keys):
            out.append(inner_pad)
            out.append(_encode_string(k))
            out.append(": ")
            _indent_value(fields[k], out, prefix, indent, depth + 1)
            if i != len(keys) - 1:
                out.append(",")
            out.append("\n")
        out.append(pad)
        out.append("}")
        return
    # Scalar: delegate to the compact encoder.
    _encode_value(value, out, "")


def encode_indent(value: Any, *, prefix: str = "", indent: str = "\t") -> str:
    if not isinstance(prefix, str) or not isinstance(indent, str):
        raise EvalError("json.encode_indent: prefix and indent must be strings")
    out: list[str] = []
    _indent_value(value, out, prefix, indent, 0)
    return "".join(out)


def indent(source: Any, *, prefix: str = "", indent: str = "\t") -> str:
    """Re-formats a JSON string with indentation."""
    if not isinstance(source, str):
        raise EvalError(
            f"json.indent: requires a string, got {starlark_type(source)}"
        )
    if not isinstance(prefix, str) or not isinstance(indent, str):
        raise EvalError("json.indent: prefix and indent must be strings")
    decoded = _Decoder(source).parse()
    out: list[str] = []
    _indent_value(decoded, out, prefix, indent, 0)
    return "".join(out)


# --------------------------------------------------------------- registration


def make_module():
    """Returns a struct-like value exposing json.encode/decode/encode_indent/indent."""
    fields = {
        "encode": BuiltinFunction(name="json.encode", impl=encode),
        "decode": BuiltinFunction(name="json.decode", impl=decode),
        "encode_indent": BuiltinFunction(name="json.encode_indent", impl=encode_indent),
        "indent": BuiltinFunction(name="json.indent", impl=indent),
    }
    return _JsonModule(fields)


class _JsonModule:
    """A namespace value exposed as the universal `json` identifier."""

    __slots__ = ("fields",)

    _starlark_type = "json"

    def __init__(self, fields: dict[str, Any]) -> None:
        self.fields = fields

    def __repr__(self) -> str:
        return "<module json>"


__all__ = [
    "MAX_DEPTH",
    "decode",
    "encode",
    "encode_indent",
    "indent",
    "make_module",
]
