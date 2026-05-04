"""Lexing, parsing, and resolution of Starlark source.

Mirrors `net.starlark.java.syntax`.
"""

from . import ast as ast  # re-export submodule
from .errors import SyntaxError as SyntaxError
from .lexer import Lexer
from .location import FileLocations, Position
from .parser import Parser, parse, parse_expression
from .resolver import Binding, Resolver, Scope, resolve
from .tokens import KEYWORDS, Token, TokenKind

__all__ = [
    "KEYWORDS",
    "Binding",
    "FileLocations",
    "Lexer",
    "Parser",
    "Position",
    "Resolver",
    "Scope",
    "SyntaxError",
    "Token",
    "TokenKind",
    "ast",
    "parse",
    "parse_expression",
    "resolve",
]
