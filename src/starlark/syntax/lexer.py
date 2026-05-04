"""Starlark scanner.

Ported from `net.starlark.java.syntax.Lexer`. Differences from the Java
reference:

- No support for Bazel doc-comment tokens (`#:` block / trailing).
- No support for the experimental type-syntax extras (`cast`, `isinstance`,
  `...`, `->`).
- No identifier interning. Python's small-string interning is good enough.
- Strings are decoded to Python `str`. Octal `\\NNN` escapes that produce a
  byte > 0x7f are stored as the corresponding Latin-1 code point — matching
  the Java reference's behavior of stuffing the raw byte into a Java `char`.
- Indexing is by Python code point, not UTF-16. We document this divergence
  in the README; it surfaces only for non-BMP characters in source files.
"""

from __future__ import annotations

from .errors import SyntaxError as StarlarkSyntaxError
from .location import FileLocations
from .tokens import KEYWORDS, Token, TokenKind

# Two-char operators where the second char is '=', mapped from first char.
_EQUAL_TOKENS: dict[str, TokenKind] = {
    "=": TokenKind.EQUALS_EQUALS,
    "!": TokenKind.NOT_EQUALS,
    ">": TokenKind.GREATER_EQUALS,
    "<": TokenKind.LESS_EQUALS,
    "+": TokenKind.PLUS_EQUALS,
    "-": TokenKind.MINUS_EQUALS,
    "*": TokenKind.STAR_EQUALS,
    "/": TokenKind.SLASH_EQUALS,
    "%": TokenKind.PERCENT_EQUALS,
    "^": TokenKind.CARET_EQUALS,
    "&": TokenKind.AMPERSAND_EQUALS,
    "|": TokenKind.PIPE_EQUALS,
}


def _is_id_start(c: str) -> bool:
    return c == "_" or ("a" <= c <= "z") or ("A" <= c <= "Z")


def _is_id_cont(c: str) -> bool:
    return _is_id_start(c) or ("0" <= c <= "9")


class Lexer:
    """Stream-style scanner. Call `next_token()` until EOF."""

    __slots__ = (
        "_check_indent",
        "_dents",
        "_indent_stack",
        "_paren_depth",
        "_pending_kind",
        "_pos",
        "_source",
        "errors",
        "locs",
    )

    def __init__(self, source: str, file: str = "<input>") -> None:
        self._source = source
        self.locs = FileLocations(file, source)
        self.errors: list[StarlarkSyntaxError] = []
        self._pos = 0
        self._indent_stack: list[int] = [0]
        self._paren_depth = 0
        self._check_indent = True
        self._dents = 0
        # Tracks the kind of the most recently emitted token so we can decide
        # whether to inject a trailing NEWLINE before EOF.
        self._pending_kind: TokenKind | None = None

    # ------------------------------------------------------------------ utils

    def _peek(self, offset: int = 0) -> str:
        i = self._pos + offset
        return self._source[i] if i < len(self._source) else ""

    def _error(self, message: str, pos: int | None = None) -> None:
        if pos is None:
            pos = self._pos
        self.errors.append(
            StarlarkSyntaxError(self.locs.position(pos), message)
        )

    # -------------------------------------------------------------- scanning

    def tokens(self):
        """Yield tokens until EOF (inclusive)."""
        while True:
            tok = self.next_token()
            yield tok
            if tok.kind == TokenKind.EOF:
                return

    def next_token(self) -> Token:
        after_newline = self._pending_kind == TokenKind.NEWLINE
        tok = self._scan_one()
        # Always emit a NEWLINE before the very first EOF, like Python.
        if tok.kind == TokenKind.EOF and not after_newline:
            tok = Token(TokenKind.NEWLINE, tok.start, tok.end)
        self._pending_kind = tok.kind
        return tok

    # The big loop. Returns one token; may emit pending INDENT/OUTDENT.
    def _scan_one(self) -> Token:
        if self._check_indent:
            self._check_indent = False
            self._compute_indentation()

        if self._dents != 0:
            if self._dents < 0:
                self._dents += 1
                p = self._pos
                return Token(TokenKind.OUTDENT, max(p - 1, 0), p)
            self._dents -= 1
            p = self._pos
            return Token(TokenKind.INDENT, max(p - 1, 0), p)

        src = self._source
        n = len(src)
        while self._pos < n:
            # Two-char operators (==, !=, +=, **, etc.) take precedence.
            two = self._try_two_char_op()
            if two is not None:
                return two

            c = src[self._pos]
            self._pos += 1

            if c == "{":
                self._paren_depth += 1
                return Token(TokenKind.LBRACE, self._pos - 1, self._pos)
            if c == "}":
                self._pop_paren()
                return Token(TokenKind.RBRACE, self._pos - 1, self._pos)
            if c == "(":
                self._paren_depth += 1
                return Token(TokenKind.LPAREN, self._pos - 1, self._pos)
            if c == ")":
                self._pop_paren()
                return Token(TokenKind.RPAREN, self._pos - 1, self._pos)
            if c == "[":
                self._paren_depth += 1
                return Token(TokenKind.LBRACKET, self._pos - 1, self._pos)
            if c == "]":
                self._pop_paren()
                return Token(TokenKind.RBRACKET, self._pos - 1, self._pos)
            if c == ":":
                return Token(TokenKind.COLON, self._pos - 1, self._pos)
            if c == ",":
                return Token(TokenKind.COMMA, self._pos - 1, self._pos)
            if c == ";":
                return Token(TokenKind.SEMI, self._pos - 1, self._pos)
            if c == "+":
                return Token(TokenKind.PLUS, self._pos - 1, self._pos)
            if c == "-":
                return Token(TokenKind.MINUS, self._pos - 1, self._pos)
            if c == "*":
                return Token(TokenKind.STAR, self._pos - 1, self._pos)
            if c == "%":
                return Token(TokenKind.PERCENT, self._pos - 1, self._pos)
            if c == "|":
                return Token(TokenKind.PIPE, self._pos - 1, self._pos)
            if c == "&":
                return Token(TokenKind.AMPERSAND, self._pos - 1, self._pos)
            if c == "^":
                return Token(TokenKind.CARET, self._pos - 1, self._pos)
            if c == "=":
                return Token(TokenKind.EQUALS, self._pos - 1, self._pos)
            if c == "~":
                return Token(TokenKind.TILDE, self._pos - 1, self._pos)
            if c == ">":
                if self._peek(0) == ">" and self._peek(1) == "=":
                    self._pos += 2
                    return Token(TokenKind.GREATER_GREATER_EQUALS, self._pos - 3, self._pos)
                if self._peek(0) == ">":
                    self._pos += 1
                    return Token(TokenKind.GREATER_GREATER, self._pos - 2, self._pos)
                return Token(TokenKind.GREATER, self._pos - 1, self._pos)
            if c == "<":
                if self._peek(0) == "<" and self._peek(1) == "=":
                    self._pos += 2
                    return Token(TokenKind.LESS_LESS_EQUALS, self._pos - 3, self._pos)
                if self._peek(0) == "<":
                    self._pos += 1
                    return Token(TokenKind.LESS_LESS, self._pos - 2, self._pos)
                return Token(TokenKind.LESS, self._pos - 1, self._pos)
            if c == "/":
                if self._peek(0) == "/" and self._peek(1) == "=":
                    self._pos += 2
                    return Token(TokenKind.SLASH_SLASH_EQUALS, self._pos - 3, self._pos)
                if self._peek(0) == "/":
                    self._pos += 1
                    return Token(TokenKind.SLASH_SLASH, self._pos - 2, self._pos)
                return Token(TokenKind.SLASH, self._pos - 1, self._pos)
            if c in (" ", "\t", "\r"):
                continue
            if c == "\\":
                # Line continuation: only valid before newline.
                if self._peek(0) == "\n":
                    self._pos += 1
                    continue
                if self._peek(0) == "\r" and self._peek(1) == "\n":
                    self._pos += 2
                    continue
                self._error(f"invalid character: {c!r}", self._pos - 1)
                return Token(TokenKind.ILLEGAL, self._pos - 1, self._pos, c)
            if c == "\n":
                if self._paren_depth > 0:
                    # Inside parens, newline is whitespace.
                    self._skip_horizontal_ws()
                    continue
                self._check_indent = True
                return Token(TokenKind.NEWLINE, self._pos - 1, self._pos)
            if c == "#":
                # Line comment: scan to (but not past) newline.
                self._scan_to_newline()
                continue
            if c in ("'", '"'):
                return self._string_literal(c, raw=False)
            if c == "r":
                nxt = self._peek(0)
                if nxt in ("'", '"'):
                    self._pos += 1
                    return self._string_literal(nxt, raw=True)
                # Fall through to identifier.
                return self._identifier_or_keyword(self._pos - 1)
            if c == "." or ("0" <= c <= "9"):
                # Unconsume; scan_number takes pos at the digit/dot.
                self._pos -= 1
                return self._scan_number_or_dot()
            if _is_id_start(c):
                return self._identifier_or_keyword(self._pos - 1)
            self._error(f"invalid character: {c!r}", self._pos - 1)
            return Token(TokenKind.ILLEGAL, self._pos - 1, self._pos, c)

        # End of input. Pop any remaining indentation as OUTDENTs preceded by a
        # synthetic NEWLINE.
        if len(self._indent_stack) > 1:
            while len(self._indent_stack) > 1:
                self._indent_stack.pop()
                self._dents -= 1
            return Token(TokenKind.NEWLINE, max(self._pos - 1, 0), self._pos)

        return Token(TokenKind.EOF, self._pos, self._pos)

    # --------------------------------------------------------------- helpers

    def _try_two_char_op(self) -> Token | None:
        n = len(self._source)
        if self._pos + 2 > n:
            return None
        c1 = self._source[self._pos]
        c2 = self._source[self._pos + 1]
        if c2 == "=":
            tk = _EQUAL_TOKENS.get(c1)
            if tk is not None:
                start = self._pos
                self._pos += 2
                return Token(tk, start, self._pos)
        elif c1 == "*" and c2 == "*":
            start = self._pos
            self._pos += 2
            return Token(TokenKind.STAR_STAR, start, self._pos)
        return None

    def _pop_paren(self) -> None:
        if self._paren_depth == 0:
            self._error("indentation error", self._pos - 1)
        else:
            self._paren_depth -= 1

    def _skip_horizontal_ws(self) -> None:
        n = len(self._source)
        while self._pos < n and self._source[self._pos] in (" ", "\t", "\r"):
            self._pos += 1

    def _scan_to_newline(self) -> None:
        n = len(self._source)
        while self._pos < n and self._source[self._pos] != "\n":
            self._pos += 1

    def _compute_indentation(self) -> None:
        """Advance over leading whitespace and (non-doc) comments at line start.

        Updates `self._dents` to (count of INDENTs) - (count of OUTDENTs).
        """
        src = self._source
        n = len(src)
        indent_len = 0
        while self._pos < n:
            c = src[self._pos]
            if c == " ":
                indent_len += 1
                self._pos += 1
            elif c == "\r":
                self._pos += 1
            elif c == "\t":
                indent_len += 1
                self._pos += 1
                self._error(
                    "tab characters are not allowed for indentation; use spaces instead",
                    self._pos,
                )
            elif c == "\n":
                indent_len = 0
                self._pos += 1
            elif c == "#":
                self._scan_to_newline()
                indent_len = 0
            else:
                break

        if self._pos == n:
            indent_len = 0  # blank trailing space; let EOF handling close levels

        top = self._indent_stack[-1]
        if top < indent_len:
            self._indent_stack.append(indent_len)
            self._dents += 1
        elif top > indent_len:
            while self._indent_stack[-1] > indent_len:
                self._indent_stack.pop()
                self._dents -= 1
            if self._indent_stack[-1] < indent_len:
                self._error("indentation error", self._pos - 1)

    def _identifier_or_keyword(self, start: int) -> Token:
        n = len(self._source)
        # Caller has already consumed the first char.
        while self._pos < n and _is_id_cont(self._source[self._pos]):
            self._pos += 1
        text = self._source[start:self._pos]
        kw = KEYWORDS.get(text)
        if kw is not None:
            return Token(kw, start, self._pos)
        return Token(TokenKind.IDENTIFIER, start, self._pos, text)

    # --------------------------------------------------------- string scanner

    def _string_literal(self, quote: str, *, raw: bool) -> Token:
        # On entry: quote has just been consumed; if raw, the leading 'r' has
        # also been consumed.
        start = self._pos - (2 if raw else 1)
        # Detect triple-quote.
        triple = False
        if self._peek(0) == quote and self._peek(1) == quote:
            self._pos += 2
            triple = True
        return self._scan_string_body(quote, raw=raw, triple=triple, start=start)

    def _scan_string_body(
        self, quote: str, *, raw: bool, triple: bool, start: int
    ) -> Token:
        out: list[str] = []
        src = self._source
        n = len(src)
        while self._pos < n:
            c = src[self._pos]
            self._pos += 1
            if c == "\n":
                if triple:
                    out.append("\n")
                    continue
                self._error("unclosed string literal", start)
                return Token(TokenKind.STRING, start, self._pos, "".join(out))
            if c == "\\":
                if self._pos >= n:
                    self._error("unclosed string literal", start)
                    return Token(TokenKind.STRING, start, self._pos, "".join(out))
                if raw:
                    out.append("\\")
                    if self._peek(0) == "\r" and self._peek(1) == "\n":
                        out.append("\n")
                        self._pos += 2
                    elif src[self._pos] in ("\r", "\n"):
                        out.append("\n")
                        self._pos += 1
                    else:
                        out.append(src[self._pos])
                        self._pos += 1
                    continue
                # Cooked escape.
                esc = src[self._pos]
                self._pos += 1
                if esc == "\n":
                    pass  # line continuation in string
                elif esc == "\r":
                    if self._peek(0) == "\n":
                        self._pos += 1
                elif esc == "a":
                    out.append("\x07")
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
                elif esc == "v":
                    out.append("\v")
                elif esc == "\\":
                    out.append("\\")
                elif esc == "'":
                    out.append("'")
                elif esc == '"':
                    out.append('"')
                elif esc == "x":
                    # Two-digit hex escape.
                    if (
                        self._pos + 1 < n
                        and _is_hex(src[self._pos])
                        and _is_hex(src[self._pos + 1])
                    ):
                        val = int(src[self._pos : self._pos + 2], 16)
                        self._pos += 2
                        out.append(chr(val))
                    else:
                        self._error("invalid \\x escape", self._pos - 2)
                        out.append("\\x")
                elif "0" <= esc <= "7":
                    val = ord(esc) - ord("0")
                    if self._pos < n and "0" <= src[self._pos] <= "7":
                        val = (val << 3) | (ord(src[self._pos]) - ord("0"))
                        self._pos += 1
                        if self._pos < n and "0" <= src[self._pos] <= "7":
                            val = (val << 3) | (ord(src[self._pos]) - ord("0"))
                            self._pos += 1
                    if val > 0xFF:
                        self._error(
                            "octal escape sequence out of range (max \\377)",
                            self._pos - 1,
                        )
                    out.append(chr(val & 0xFF))
                else:
                    self._error(
                        f"invalid escape sequence: \\{esc}. Use '\\\\' to insert '\\'.",
                        self._pos - 1,
                    )
                    out.append("\\")
                    out.append(esc)
                continue
            if c == quote:
                if triple:
                    if self._peek(0) == quote and self._peek(1) == quote:
                        self._pos += 2
                        return Token(TokenKind.STRING, start, self._pos, "".join(out))
                    out.append(c)
                    continue
                return Token(TokenKind.STRING, start, self._pos, "".join(out))
            out.append(c)

        self._error("unclosed string literal", start)
        return Token(TokenKind.STRING, start, self._pos, "".join(out))

    # --------------------------------------------------------- number scanner

    def _scan_number_or_dot(self) -> Token:
        src = self._source
        n = len(src)
        start = self._pos
        c = src[self._pos]
        fraction = False
        exponent = False

        if c == ".":
            # `.` or fraction.
            if not (start + 1 < n and "0" <= src[start + 1] <= "9"):
                self._pos += 1
                return Token(TokenKind.DOT, start, self._pos)
            fraction = True
            # Don't consume yet; fall through to fraction branch.
        elif c == "0":
            self._pos += 1
            if self._pos < n:
                nx = src[self._pos]
                if nx in ("x", "X"):
                    self._pos += 1
                    if not (self._pos < n and _is_hex(src[self._pos])):
                        self._error("invalid hex literal", start)
                    while self._pos < n and _is_hex(src[self._pos]):
                        self._pos += 1
                    return _make_int(start, self._pos, src)
                if nx in ("o", "O"):
                    self._pos += 1
                    while self._pos < n and "0" <= src[self._pos] <= "7":
                        self._pos += 1
                    return _make_int(start, self._pos, src)
                if nx in ("b", "B"):
                    self._pos += 1
                    if not (self._pos < n and src[self._pos] in ("0", "1")):
                        self._error("invalid binary literal", start)
                    while self._pos < n and src[self._pos] in ("0", "1"):
                        self._pos += 1
                    return _make_int(start, self._pos, src)
                # "0", obsolete octal-like decimal "0755", or float.
                while self._pos < n and "0" <= src[self._pos] <= "9":
                    self._pos += 1
                if self._pos < n and src[self._pos] == ".":
                    fraction = True
                elif self._pos < n and src[self._pos] in ("e", "E"):
                    exponent = True
                # Reject leading-zero non-zero decimals (e.g. "0755").
                if not fraction and not exponent:
                    text = src[start : self._pos]
                    if len(text) > 1 and any(d != "0" for d in text):
                        self._error(
                            f"invalid octal literal: {text} (use '0o{text.lstrip('0')}')",
                            start,
                        )
        else:
            # Decimal.
            self._pos += 1
            while self._pos < n and "0" <= src[self._pos] <= "9":
                self._pos += 1
            if self._pos < n and src[self._pos] == ".":
                fraction = True
            elif self._pos < n and src[self._pos] in ("e", "E"):
                exponent = True

        if fraction:
            self._pos += 1  # consume '.'
            while self._pos < n and "0" <= src[self._pos] <= "9":
                self._pos += 1
            if self._pos < n and src[self._pos] in ("e", "E"):
                exponent = True

        if exponent:
            self._pos += 1  # consume e/E
            if self._pos < n and src[self._pos] in ("+", "-"):
                self._pos += 1
            while self._pos < n and "0" <= src[self._pos] <= "9":
                self._pos += 1

        if fraction or exponent:
            text = src[start : self._pos]
            try:
                value = float(text)
            except ValueError:
                self._error("invalid float literal", start)
                value = 0.0
            return Token(TokenKind.FLOAT, start, self._pos, value)

        return _make_int(start, self._pos, src)


def _is_hex(c: str) -> bool:
    return ("0" <= c <= "9") or ("a" <= c <= "f") or ("A" <= c <= "F")


def _make_int(start: int, end: int, src: str) -> Token:
    text = src[start:end]
    if len(text) > 1 and text[0] == "0" and text[1] in ("x", "X"):
        value = int(text, 16)
    elif len(text) > 1 and text[0] == "0" and text[1] in ("o", "O"):
        value = int(text, 8)
    elif len(text) > 1 and text[0] == "0" and text[1] in ("b", "B"):
        value = int(text, 2)
    elif len(text) > 1 and text[0] == "0":
        # The lexer has already reported leading-zero decimals as an error.
        # We still need a value to keep the parser making progress; treat
        # it as decimal.
        value = int(text, 10)
    else:
        value = int(text, 10)
    return Token(TokenKind.INT, start, end, value)
