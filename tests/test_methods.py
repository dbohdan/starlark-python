"""Tests for string and collection methods (Phases 8 + 9)."""

from __future__ import annotations

import pytest

import starlark
from starlark.eval import EvalError, StarlarkSet


def expr(source: str):
    return starlark.eval(source)


def run(source: str):
    return starlark.exec_file(source)


# ----------------------------------------------------------- string


def test_startswith_endswith():
    assert expr("'hello'.startswith('he')") is True
    assert expr("'hello'.startswith('lo')") is False
    assert expr("'hello'.endswith('lo')") is True
    # Tuple forms
    assert expr("'hello'.startswith(('he', 'lo'))") is True


def test_find_rfind_index():
    assert expr("'hello'.find('l')") == 2
    assert expr("'hello'.rfind('l')") == 3
    assert expr("'hello'.find('z')") == -1
    assert expr("'hello'.index('l')") == 2


def test_count():
    assert expr("'banana'.count('a')") == 3


def test_case_methods():
    assert expr("'Hello'.lower()") == "hello"
    assert expr("'Hello'.upper()") == "HELLO"
    assert expr("'hello world'.capitalize()") == "Hello world"
    assert expr("'hello world'.title()") == "Hello World"


def test_strip_methods():
    assert expr("'  hi  '.strip()") == "hi"
    assert expr("'..hi..'.strip('.')") == "hi"
    assert expr("'  hi'.lstrip()") == "hi"
    assert expr("'hi  '.rstrip()") == "hi"


def test_split_join():
    v = expr("'a,b,c'.split(',')")
    assert list(v) == ["a", "b", "c"]
    assert expr("','.join(['a', 'b', 'c'])") == "a,b,c"


def test_splitlines():
    v = expr("'a\\nb\\nc'.splitlines()")
    assert list(v) == ["a", "b", "c"]


def test_replace():
    assert expr("'foofoo'.replace('foo', 'bar')") == "barbar"
    assert expr("'foofoo'.replace('foo', 'bar', 1)") == "barfoo"


def test_predicates():
    assert expr("'abc'.isalpha()") is True
    assert expr("'abc1'.isalpha()") is False
    assert expr("'abc1'.isalnum()") is True
    assert expr("'123'.isdigit()") is True
    assert expr("'abc'.islower()") is True
    assert expr("'ABC'.isupper()") is True


def test_format_method():
    assert expr("'{}-{}'.format('a', 'b')") == "a-b"
    assert expr("'{0}-{0}'.format('x')") == "x-x"
    assert expr("'{name}'.format(name='alice')") == "alice"
    assert expr("'{!r}'.format('hi')") == '"hi"'


def test_remove_prefix_suffix():
    assert expr("'foobar'.removeprefix('foo')") == "bar"
    assert expr("'foobar'.removeprefix('xx')") == "foobar"
    assert expr("'foobar'.removesuffix('bar')") == "foo"


def test_partition():
    assert expr("'a-b-c'.partition('-')") == ("a", "-", "b-c")
    assert expr("'a-b-c'.rpartition('-')") == ("a-b", "-", "c")


def test_elems():
    v = expr("'abc'.elems()")
    assert list(v) == ["a", "b", "c"]


def test_elem_ords():
    v = expr("'Hello'.elem_ords()")
    assert list(v) == [72, 101, 108, 108, 111]
    # non-ASCII
    v2 = expr("'世'.elem_ords()")
    assert list(v2) == [0xE4, 0xB8, 0x96]  # UTF-8 bytes


def test_codepoints():
    v = expr("'Hello'.codepoints()")
    assert list(v) == ["H", "e", "l", "l", "o"]
    v2 = expr("'世'.codepoints()")
    assert list(v2) == ["世"]


def test_codepoint_ords():
    v = expr("'Hello'.codepoint_ords()")
    assert list(v) == [72, 101, 108, 108, 111]
    v2 = expr("'世'.codepoint_ords()")
    assert list(v2) == [0x4E16]  # 19990


# ----------------------------------------------------------- list


def test_list_append_extend():
    m = run("a = [1, 2]\na.append(3)\na.extend([4, 5])\n")
    assert list(m.globals["a"]) == [1, 2, 3, 4, 5]


def test_list_pop():
    m = run("a = [1, 2, 3]\nx = a.pop()\ny = a.pop(0)\n")
    assert m.globals["x"] == 3
    assert m.globals["y"] == 1
    assert list(m.globals["a"]) == [2]


def test_list_remove_clear():
    m = run("a = [1, 2, 3, 2]\na.remove(2)\nb = list(a)\na.clear()\n")
    assert list(m.globals["b"]) == [1, 3, 2]
    assert list(m.globals["a"]) == []


def test_list_index_count():
    assert expr("[1, 2, 3, 2].index(2)") == 1
    assert expr("[1, 2, 3, 2].count(2)") == 2


def test_list_insert():
    m = run("a = [1, 3]\na.insert(1, 2)\n")
    assert list(m.globals["a"]) == [1, 2, 3]


# ----------------------------------------------------------- dict


def test_dict_get_setdefault():
    assert expr("{'a': 1}.get('a')") == 1
    assert expr("{'a': 1}.get('b', 'def')") == "def"
    m = run("d = {'a': 1}\nv = d.setdefault('b', 2)\n")
    assert m.globals["v"] == 2
    assert m.globals["d"]["b"] == 2


def test_dict_keys_values_items():
    v = expr("{'a': 1, 'b': 2}.keys()")
    assert sorted(list(v)) == ["a", "b"]
    assert sorted(list(expr("{'a': 1, 'b': 2}.values()"))) == [1, 2]
    items = list(expr("{'a': 1, 'b': 2}.items()"))
    assert sorted(items) == [("a", 1), ("b", 2)]


def test_dict_update_pop():
    m = run("d = {'a': 1}\nd.update(b=2, c=3)\nv = d.pop('a')\n")
    assert m.globals["v"] == 1
    assert "b" in m.globals["d"]


def test_dict_clear():
    m = run("d = {'a': 1}\nd.clear()\n")
    assert len(m.globals["d"]) == 0


# ----------------------------------------------------------- set


def test_set_add_remove():
    m = run("s = set([1, 2, 3])\ns.add(4)\ns.remove(2)\n")
    s = m.globals["s"]
    assert isinstance(s, StarlarkSet)
    assert 4 in s
    assert 2 not in s


def test_set_union_intersect_diff():
    a = expr("set([1, 2, 3]).union(set([3, 4]))")
    assert sorted(list(a)) == [1, 2, 3, 4]
    b = expr("set([1, 2, 3]).intersection(set([2, 3, 4]))")
    assert sorted(list(b)) == [2, 3]
    c = expr("set([1, 2, 3]).difference(set([2, 3]))")
    assert list(c) == [1]


# ----------------------------------------------------------- attr lookup


def test_hasattr_uses_method_table():
    assert expr("hasattr('hi', 'upper')") is True
    assert expr("hasattr([], 'append')") is True
    assert expr("hasattr({}, 'keys')") is True
    assert expr("hasattr(1, 'append')") is False


# ----------------------------------------------------------- %c format guard


def test_percent_c_out_of_range_raises_evalerror():
    # `chr()` is guarded in the builtin; the `%c` format branch must guard too,
    # else a raw ValueError (out of range) or OverflowError (oversized) leaks.
    with pytest.raises(EvalError, match="range"):
        expr("'%c' % 1114112")
    with pytest.raises(EvalError, match="range"):
        expr("'%c' % 1000000000000")
    with pytest.raises(EvalError, match="range"):
        expr("'%c' % -1")


def test_percent_c_in_range_still_works():
    assert expr("'%c' % 65") == "A"
    assert expr("'%c' % 0x10FFFF") == chr(0x10FFFF)


# ----------------------------------------------------------- oversized ints


def test_oversized_int_stringification_raises_evalerror():
    # CPython caps decimal int<->str conversion at int_max_str_digits (4300).
    # Build an int well past that (~9.6k digits) arithmetically — a decimal
    # literal that large would itself trip the cap at parse time — and confirm
    # every stringifying path surfaces a clean EvalError, not a raw ValueError.
    base = "x = 1 << 500\nfor i in range(6):\n    x = x * x\n"
    for tail in ("y = str(x)", "y = repr(x)", "y = '%d' % x", "y = '{}'.format(x)"):
        with pytest.raises(EvalError, match="too large"):
            run(base + tail + "\n")


def test_modest_int_stringification_still_works():
    assert expr("str(1 << 500)") == str(1 << 500)
    assert expr("'%d' % 255") == "255"
    assert expr("'%x' % 255") == "ff"
