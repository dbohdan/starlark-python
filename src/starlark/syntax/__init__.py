"""Lexing, parsing, and resolution of Starlark source.

Mirrors `net.starlark.java.syntax`.
"""

from .errors import SyntaxError as SyntaxError  # re-export
from .lexer import Lexer
from .location import FileLocations, Position
from .tokens import KEYWORDS, Token, TokenKind

__all__ = [
    "KEYWORDS",
    "FileLocations",
    "Lexer",
    "Position",
    "SyntaxError",
    "Token",
    "TokenKind",
]
