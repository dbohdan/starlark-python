"""Tests for the lexer."""

from __future__ import annotations

import pytest

from starlark.syntax import Lexer, TokenKind


def kinds(source: str) -> list[TokenKind]:
    return [tok.kind for tok in Lexer(source).tokens()]


def values(source: str) -> list[tuple[TokenKind, object]]:
    return [(tok.kind, tok.value) for tok in Lexer(source).tokens()]


def test_empty():
    assert kinds("") == [TokenKind.NEWLINE, TokenKind.EOF]


def test_simple_arith():
    toks = list(Lexer("1 + 2").tokens())
    assert [t.kind for t in toks] == [
        TokenKind.INT,
        TokenKind.PLUS,
        TokenKind.INT,
        TokenKind.NEWLINE,
        TokenKind.EOF,
    ]
    assert toks[0].value == 1
    assert toks[2].value == 2


def test_int_radixes():
    toks = list(Lexer("0x1F 0o17 0b101 42").tokens())
    nums = [t.value for t in toks if t.kind == TokenKind.INT]
    assert nums == [0x1F, 0o17, 0b101, 42]


def test_float_literals():
    toks = list(Lexer("1.5 .25 1e3 2.5e-2").tokens())
    nums = [t.value for t in toks if t.kind == TokenKind.FLOAT]
    assert nums == [1.5, 0.25, 1e3, 2.5e-2]


def test_keywords_vs_identifiers():
    toks = list(Lexer("def foo and orange or").tokens())
    ks = [t.kind for t in toks]
    assert ks[:5] == [
        TokenKind.DEF,
        TokenKind.IDENTIFIER,
        TokenKind.AND,
        TokenKind.IDENTIFIER,
        TokenKind.OR,
    ]
    # `orange` is an identifier — should not lex as `or` + `ange`.
    assert toks[3].value == "orange"


def test_string_simple():
    toks = list(Lexer('"hello"').tokens())
    assert toks[0].kind == TokenKind.STRING
    assert toks[0].value == "hello"


def test_string_escapes():
    toks = list(Lexer(r'"a\n\t\\\""').tokens())
    assert toks[0].value == 'a\n\t\\"'


def test_string_raw():
    toks = list(Lexer(r'r"a\nb"').tokens())
    # Raw strings keep the backslash literal.
    assert toks[0].value == "a\\nb"


def test_string_octal_escape():
    # \101 = 'A', \377 = code point 0xFF.
    toks = list(Lexer(r'"\101 \377"').tokens())
    assert toks[0].value == "A \xff"


def test_string_hex_escape():
    toks = list(Lexer(r'"\x41\x7e"').tokens())
    assert toks[0].value == "A~"


def test_string_triple_double():
    src = '"""line1\nline2"""'
    toks = list(Lexer(src).tokens())
    assert toks[0].kind == TokenKind.STRING
    assert toks[0].value == "line1\nline2"


def test_string_triple_single():
    src = "'''abc'''"
    toks = list(Lexer(src).tokens())
    assert toks[0].value == "abc"


def test_unclosed_string_reports_error():
    lex = Lexer('"abc')
    list(lex.tokens())
    assert lex.errors
    assert "unclosed string literal" in lex.errors[0].message


def test_indent_outdent():
    src = "def f():\n    return 1\n"
    ks = kinds(src)
    assert TokenKind.INDENT in ks
    assert TokenKind.OUTDENT in ks


def test_indentation_nested():
    src = "if x:\n    if y:\n        a\n    b\nc\n"
    ks = kinds(src)
    # Two INDENTs, two OUTDENTs.
    assert ks.count(TokenKind.INDENT) == 2
    assert ks.count(TokenKind.OUTDENT) == 2


def test_indent_inside_parens_is_whitespace():
    src = "(1,\n    2,\n    3)\n"
    ks = kinds(src)
    assert TokenKind.INDENT not in ks
    assert TokenKind.OUTDENT not in ks


def test_two_char_operators():
    toks = list(Lexer("a += 1 == 2 != 3 << 4 >> 5 // 6 ** 7").tokens())
    seen = {t.kind for t in toks}
    expected = {
        TokenKind.IDENTIFIER,
        TokenKind.PLUS_EQUALS,
        TokenKind.EQUALS_EQUALS,
        TokenKind.NOT_EQUALS,
        TokenKind.LESS_LESS,
        TokenKind.GREATER_GREATER,
        TokenKind.SLASH_SLASH,
        TokenKind.STAR_STAR,
        TokenKind.INT,
        TokenKind.NEWLINE,
        TokenKind.EOF,
    }
    assert expected.issubset(seen)


def test_line_continuation():
    toks = list(Lexer("a + \\\nb\n").tokens())
    ks = [t.kind for t in toks]
    # No NEWLINE between '+' and 'b'.
    assert ks == [
        TokenKind.IDENTIFIER,
        TokenKind.PLUS,
        TokenKind.IDENTIFIER,
        TokenKind.NEWLINE,
        TokenKind.EOF,
    ]


def test_comment_skipped():
    toks = list(Lexer("a # this is a comment\nb\n").tokens())
    ks = [t.kind for t in toks]
    assert ks == [
        TokenKind.IDENTIFIER,
        TokenKind.NEWLINE,
        TokenKind.IDENTIFIER,
        TokenKind.NEWLINE,
        TokenKind.EOF,
    ]


def test_dot_vs_ellipsis_vs_number():
    # `...` is not in our token set; we lex a single DOT then attempt the next.
    toks = list(Lexer("a.b 1.5 .25").tokens())
    seen_kinds = [t.kind for t in toks]
    assert TokenKind.DOT in seen_kinds
    floats = [t.value for t in toks if t.kind == TokenKind.FLOAT]
    assert floats == [1.5, 0.25]


def test_position_tracking():
    lex = Lexer("a\nbb\nccc")
    toks = list(lex.tokens())
    # First identifier at line 1, second at line 2, third at line 3.
    a = toks[0]
    bb = next(t for t in toks if t.kind == TokenKind.IDENTIFIER and t.value == "bb")
    ccc = next(t for t in toks if t.kind == TokenKind.IDENTIFIER and t.value == "ccc")
    assert lex.locs.position(a.start).line == 1
    assert lex.locs.position(bb.start).line == 2
    assert lex.locs.position(ccc.start).line == 3


def test_leading_zero_decimal_is_error():
    lex = Lexer("x = 0755\n")
    list(lex.tokens())
    assert any("invalid octal literal" in e.message for e in lex.errors)


def test_zero_alone_is_fine():
    lex = Lexer("x = 0\n")
    list(lex.tokens())
    assert not lex.errors


def test_tab_indent_reports_error():
    lex = Lexer("def f():\n\treturn 1\n")
    list(lex.tokens())
    assert any("tab" in e.message.lower() for e in lex.errors)


@pytest.mark.parametrize(
    "src,expected",
    [
        ("True", [TokenKind.IDENTIFIER, TokenKind.NEWLINE, TokenKind.EOF]),
        ("None", [TokenKind.IDENTIFIER, TokenKind.NEWLINE, TokenKind.EOF]),
        ("a:b", [TokenKind.IDENTIFIER, TokenKind.COLON, TokenKind.IDENTIFIER,
                 TokenKind.NEWLINE, TokenKind.EOF]),
    ],
)
def test_misc(src, expected):
    assert kinds(src) == expected
