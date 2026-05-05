"""Tests for the json module."""

from __future__ import annotations

import pytest

import starlark
from starlark.eval import EvalError


def expr(source: str):
    return starlark.eval(source)


def run(source: str):
    return starlark.exec_file(source)


# ---------------------------------------------------------------- encode


def test_encode_scalars():
    assert expr("json.encode(None)") == "null"
    assert expr("json.encode(True)") == "true"
    assert expr("json.encode(False)") == "false"
    assert expr("json.encode(42)") == "42"
    assert expr("json.encode(-1)") == "-1"


def test_encode_string():
    assert expr('json.encode("hello")') == '"hello"'
    assert expr(r'json.encode("a\nb")') == '"a\\nb"'
    assert expr(r'json.encode("tab\there")') == '"tab\\there"'
    # Quote escaping.
    assert expr('json.encode("she said \\"hi\\"")') == '"she said \\"hi\\""'


def test_encode_control_chars():
    # U+0001 must be escaped as .
    out = expr(r'json.encode("\x01")')
    assert out == '"\\u0001"'


def test_encode_list_tuple_range():
    assert expr("json.encode([1, 2, 3])") == "[1,2,3]"
    assert expr("json.encode((1, 2, 3))") == "[1,2,3]"
    assert expr("json.encode(range(3))") == "[0,1,2]"
    assert expr("json.encode([])") == "[]"


def test_encode_dict_sorts_keys():
    # Insertion order is b, a; output must be a, b.
    assert expr('json.encode({"b": 2, "a": 1})') == '{"a":1,"b":2}'


def test_encode_arbitrary_precision_int():
    assert expr("json.encode(12345 * 12345 * 12345)") == "1881365963625"


def test_encode_rejects_nan_inf():
    with pytest.raises(EvalError, match="non-finite"):
        expr('json.encode(float("nan"))')
    with pytest.raises(EvalError, match="non-finite"):
        expr('json.encode(float("inf"))')


def test_encode_rejects_non_string_dict_keys():
    with pytest.raises(EvalError, match="dict has int key"):
        expr('json.encode({1: "x"})')


def test_encode_rejects_callables_and_sets():
    with pytest.raises(EvalError, match="cannot encode builtin_function_or_method"):
        expr("json.encode(len)")
    with pytest.raises(EvalError, match="cannot encode set"):
        expr("json.encode(set([1, 2]))")


def test_encode_path_in_error():
    # Nested error location should include the path through the value.
    with pytest.raises(EvalError, match="at list index 1"):
        expr('json.encode([1, len])')


# ---------------------------------------------------------------- decode


def test_decode_scalars():
    assert expr('json.decode("null")') is None
    assert expr('json.decode("true")') is True
    assert expr('json.decode("false")') is False
    assert expr('json.decode("42")') == 42
    assert expr('json.decode("-1.5")') == -1.5


def test_decode_string():
    assert expr(r'json.decode("\"hello\"")') == "hello"
    assert expr(r'json.decode("\"a\\nb\"")') == "a\nb"
    assert expr(r'json.decode("\"\\u00e9\"")') == "\xe9"


def test_decode_list():
    v = expr('json.decode("[1, 2, 3]")')
    assert list(v) == [1, 2, 3]


def test_decode_object():
    v = expr('json.decode("{\\"a\\": 1, \\"b\\": 2}")')
    assert v["a"] == 1
    assert v["b"] == 2


def test_decode_nested():
    v = expr('json.decode("{\\"x\\": [1, {\\"y\\": 2}]}")')
    inner = list(v["x"])
    assert inner[0] == 1
    assert inner[1]["y"] == 2


def test_decode_rejects_trailing_data():
    with pytest.raises(EvalError, match="trailing data"):
        expr('json.decode("1 2")')


def test_decode_rejects_unterminated_string():
    with pytest.raises(EvalError, match="unterminated"):
        expr(r'json.decode("\"abc")')


def test_decode_rejects_control_chars_in_string():
    # Literal newline inside string is invalid JSON.
    src = '"a\nb"'
    with pytest.raises(EvalError, match="control character"):
        expr(f'json.decode({src!r})')


def test_decode_rejects_dangling_escape():
    with pytest.raises(EvalError, match="dangling escape"):
        expr(r'json.decode("\"abc\\")')


def test_decode_rejects_invalid_unicode_escape():
    with pytest.raises(EvalError, match="invalid"):
        expr(r'json.decode("\"\\uZZZZ\"")')


def test_decode_handles_surrogate_pair():
    # 😹 == U+1F639 (😹).
    v = expr(r'json.decode("\"\\uD83D\\uDE39\"")')
    assert v == "\U0001F639"


def test_decode_rejects_unpaired_surrogate():
    with pytest.raises(EvalError, match="surrogate"):
        expr(r'json.decode("\"\\uD83D\"")')


def test_decode_depth_limit_protection():
    # 1000-deep array should be rejected before stack-overflow.
    deep = "[" * 1000 + "]" * 1000
    with pytest.raises(EvalError, match="too deep"):
        starlark.eval(f"json.decode({deep!r})")


def test_decode_invalid_number():
    with pytest.raises(EvalError, match="invalid number"):
        expr('json.decode("01")')
    with pytest.raises(EvalError, match="invalid number"):
        expr('json.decode("1.")')


# ---------------------------------------------------------------- indent


def test_encode_indent_basic():
    out = expr('json.encode_indent([1, 2, 3])')
    assert out == "[\n\t1,\n\t2,\n\t3\n]"


def test_encode_indent_nested():
    out = expr('json.encode_indent({"a": [1, 2]})')
    assert "\n" in out
    assert '"a"' in out


def test_encode_indent_with_prefix():
    out = expr('json.encode_indent([1, 2], prefix=">", indent="  ")')
    assert out == "[\n>  1,\n>  2\n>]"


def test_indent_existing_json():
    assert expr('json.indent("[1,2,3]")') == "[\n\t1,\n\t2,\n\t3\n]"


# ---------------------------------------------------------------- module surface


def test_dir_lists_module_methods():
    v = expr("dir(json)")
    assert sorted(list(v)) == ["decode", "encode", "encode_indent", "indent"]


def test_indent_validates_arg_types():
    with pytest.raises(EvalError, match="requires a string"):
        expr("json.indent(42)")


# ---------------------------------------------------------------- round trip


def test_round_trip():
    m = run(
        'x = {"a": [1, 2, 3], "b": "hi", "c": None, "d": True}\n'
        "encoded = json.encode(x)\n"
        "y = json.decode(encoded)\n"
    )
    encoded = m.globals["encoded"]
    assert isinstance(encoded, str)
    # Stable sorted keys.
    assert encoded == '{"a":[1,2,3],"b":"hi","c":null,"d":true}'
