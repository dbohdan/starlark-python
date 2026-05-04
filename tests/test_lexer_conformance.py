"""Smoke-test the lexer against every .star conformance file.

Phase-1 goal: each file must lex without raising and end in EOF. Whether the
errors list is populated is OK to assert per-file once the lexer is more
thoroughly exercised; for now we just sanity-check tokenization completes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from starlark.syntax import Lexer, TokenKind

CONFORMANCE_DIR = Path(__file__).parent.parent / "conformance"
STAR_FILES = sorted(CONFORMANCE_DIR.glob("*.star"))


@pytest.mark.parametrize("path", STAR_FILES, ids=lambda p: p.name)
def test_lex_to_completion(path: Path):
    source = path.read_text(encoding="utf-8")
    lex = Lexer(source, file=path.name)
    toks = list(lex.tokens())
    assert toks[-1].kind == TokenKind.EOF
    # The lexer should not produce ILLEGAL tokens on these well-formed files.
    assert not any(t.kind == TokenKind.ILLEGAL for t in toks), lex.errors
    # And it should report no syntax errors.
    assert not lex.errors, [str(e) for e in lex.errors[:5]]
