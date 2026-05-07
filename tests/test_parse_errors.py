"""Top-level `parse` / `parse_expression` raise on errors.

The lower-level `Parser` class methods continue to collect errors into
`StarlarkFile.errors` without raising, so error-recovery tooling and
IDE-style consumers still have a non-raising API.
"""

from __future__ import annotations

import pytest

from starlark import StarlarkSyntaxError, StarlarkSyntaxException
from starlark.syntax import Lexer, Parser, parse, parse_expression

# --------------------------------------------------------------- parse


def test_parse_raises_on_lex_error():
    with pytest.raises(StarlarkSyntaxException):
        parse('"unterminated')


def test_parse_raises_on_parse_error():
    with pytest.raises(StarlarkSyntaxException):
        parse("def 1: pass\n")


def test_parse_succeeds_on_valid_source():
    f = parse("x = 1\n")
    assert f.errors == []
    assert len(f.statements) == 1


def test_parse_exception_carries_errors_list():
    with pytest.raises(StarlarkSyntaxException) as exc_info:
        parse("x = 1 < 2 < 3\n")
    assert all(isinstance(e, StarlarkSyntaxError) for e in exc_info.value.errors)
    assert any("not associative" in e.message for e in exc_info.value.errors)


# --------------------------------------------------------------- parse_expression


def test_parse_expression_raises_on_lex_error():
    with pytest.raises(StarlarkSyntaxException):
        parse_expression('"unterminated')


def test_parse_expression_raises_on_parse_error():
    with pytest.raises(StarlarkSyntaxException):
        parse_expression("***")


def test_parse_expression_no_longer_raises_value_error():
    """Regression test: lex errors used to raise `ValueError`, forcing
    callers like remarshal to catch both ValueError and
    StarlarkSyntaxException. They should only need to catch the latter."""
    try:
        parse_expression('"unterminated')
    except StarlarkSyntaxException:
        pass  # expected
    except ValueError as e:
        pytest.fail(f"parse_expression should not raise plain ValueError: {e}")


def test_parse_expression_succeeds_on_valid_input():
    e = parse_expression("1 + 2")
    assert e is not None


# --------------------------------------------------------------- lower level


def test_parser_class_still_returns_errors_in_file():
    """Lower-level form: error-recovery / IDE tooling needs the
    error-list shape, not raises."""
    f = Parser(Lexer("x = 1 < 2 < 3\n")).parse_file()
    assert any("not associative" in e.message for e in f.errors)


def test_parser_class_parse_expression_collects_errors_too():
    lexer = Lexer('"unterminated')
    Parser(lexer).parse_expression()
    # Lexer errors are shared with parser errors.
    assert lexer.errors
