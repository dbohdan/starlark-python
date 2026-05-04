"""Token kinds and the Token record produced by the lexer.

Mirrors `net.starlark.java.syntax.TokenKind`, minus Bazel-only doc-comment
tokens (`#:` block / trailing) and the experimental type-syntax extras
(`cast`, `isinstance`, `...`, `->`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class TokenKind(Enum):
    AMPERSAND = "&"
    AMPERSAND_EQUALS = "&="
    AND = "and"
    AS = "as"
    ASSERT = "assert"
    BREAK = "break"
    CARET = "^"
    CARET_EQUALS = "^="
    CLASS = "class"
    COLON = ":"
    COMMA = ","
    CONTINUE = "continue"
    DEF = "def"
    DEL = "del"
    DOT = "."
    ELIF = "elif"
    ELSE = "else"
    EOF = "EOF"
    EQUALS = "="
    EQUALS_EQUALS = "=="
    EXCEPT = "except"
    FINALLY = "finally"
    FLOAT = "float literal"
    FOR = "for"
    FROM = "from"
    GLOBAL = "global"
    GREATER = ">"
    GREATER_EQUALS = ">="
    GREATER_GREATER = ">>"
    GREATER_GREATER_EQUALS = ">>="
    IDENTIFIER = "identifier"
    IF = "if"
    ILLEGAL = "illegal character"
    IMPORT = "import"
    IN = "in"
    INDENT = "indent"
    INT = "integer literal"
    IS = "is"
    LAMBDA = "lambda"
    LBRACE = "{"
    LBRACKET = "["
    LESS = "<"
    LESS_EQUALS = "<="
    LESS_LESS = "<<"
    LESS_LESS_EQUALS = "<<="
    LOAD = "load"
    LPAREN = "("
    MINUS = "-"
    MINUS_EQUALS = "-="
    NEWLINE = "newline"
    NONLOCAL = "nonlocal"
    NOT = "not"
    NOT_EQUALS = "!="
    NOT_IN = "not in"
    OR = "or"
    OUTDENT = "outdent"
    PASS = "pass"
    PERCENT = "%"
    PERCENT_EQUALS = "%="
    PIPE = "|"
    PIPE_EQUALS = "|="
    PLUS = "+"
    PLUS_EQUALS = "+="
    RAISE = "raise"
    RBRACE = "}"
    RBRACKET = "]"
    RETURN = "return"
    RPAREN = ")"
    SEMI = ";"
    SLASH = "/"
    SLASH_EQUALS = "/="
    SLASH_SLASH = "//"
    SLASH_SLASH_EQUALS = "//="
    STAR = "*"
    STAR_EQUALS = "*="
    STAR_STAR = "**"
    STRING = "string literal"
    TILDE = "~"
    TRY = "try"
    WHILE = "while"
    WITH = "with"
    YIELD = "yield"

    def __str__(self) -> str:
        return self.value


KEYWORDS: dict[str, TokenKind] = {
    "and": TokenKind.AND,
    "as": TokenKind.AS,
    "assert": TokenKind.ASSERT,
    "break": TokenKind.BREAK,
    "class": TokenKind.CLASS,
    "continue": TokenKind.CONTINUE,
    "def": TokenKind.DEF,
    "del": TokenKind.DEL,
    "elif": TokenKind.ELIF,
    "else": TokenKind.ELSE,
    "except": TokenKind.EXCEPT,
    "finally": TokenKind.FINALLY,
    "for": TokenKind.FOR,
    "from": TokenKind.FROM,
    "global": TokenKind.GLOBAL,
    "if": TokenKind.IF,
    "import": TokenKind.IMPORT,
    "in": TokenKind.IN,
    "is": TokenKind.IS,
    "lambda": TokenKind.LAMBDA,
    "load": TokenKind.LOAD,
    "nonlocal": TokenKind.NONLOCAL,
    "not": TokenKind.NOT,
    "or": TokenKind.OR,
    "pass": TokenKind.PASS,
    "raise": TokenKind.RAISE,
    "return": TokenKind.RETURN,
    "try": TokenKind.TRY,
    "while": TokenKind.WHILE,
    "with": TokenKind.WITH,
    "yield": TokenKind.YIELD,
}


@dataclass(frozen=True, slots=True)
class Token:
    """One lexical token. `start` and `end` are character offsets in the source."""

    kind: TokenKind
    start: int
    end: int
    value: Any = None
