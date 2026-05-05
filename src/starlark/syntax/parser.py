"""Recursive-descent parser for Starlark.

Ported from `net.starlark.java.syntax.Parser`. Produces the AST defined in
`ast.py`.

Differences from the Java reference:

- No `cast`, `isinstance`, `...`, `->` (experimental type syntax).
- No doc-comment attachment.
- No type annotations on parameters, no var-statement, no type-alias statement.
- No string-literal interning (Python's small-string interning suffices).
- No statement-by-statement error recovery beyond `syncTo`/`syncPast`. Parse
  errors are still collected; the AST may be partial when errors are present.
"""

from __future__ import annotations

from . import ast
from .ast import (
    Argument,
    AssignmentStatement,
    BinaryOperatorExpression,
    CallExpression,
    Comprehension,
    ComprehensionClauseFor,
    ComprehensionClauseIf,
    ConditionalExpression,
    DefStatement,
    DictEntry,
    DictExpression,
    DotExpression,
    Expression,
    ExpressionStatement,
    FloatLiteral,
    FlowStatement,
    ForStatement,
    Identifier,
    IfStatement,
    IndexExpression,
    IntLiteral,
    KeywordArgument,
    LambdaExpression,
    ListExpression,
    LoadBinding,
    LoadStatement,
    MandatoryParameter,
    OptionalParameter,
    Parameter,
    PositionalArgument,
    ReturnStatement,
    SliceExpression,
    StarArgument,
    StarlarkFile,
    StarParameter,
    StarStarArgument,
    StarStarParameter,
    Statement,
    StringLiteral,
    UnaryOperatorExpression,
)
from .errors import StarlarkSyntaxException
from .errors import SyntaxError as StarlarkSyntaxError
from .lexer import Lexer
from .tokens import Token, TokenKind

# ----------------------------------------------------------- terminator sets

STATEMENT_TERMINATORS = frozenset({TokenKind.EOF, TokenKind.NEWLINE, TokenKind.SEMI})
LIST_TERMINATORS = frozenset({TokenKind.EOF, TokenKind.RBRACKET, TokenKind.SEMI})
DICT_TERMINATORS = frozenset({TokenKind.EOF, TokenKind.RBRACE, TokenKind.SEMI})
EXPR_LIST_TERMINATORS = frozenset(
    {
        TokenKind.EOF,
        TokenKind.NEWLINE,
        TokenKind.EQUALS,
        TokenKind.RBRACE,
        TokenKind.RBRACKET,
        TokenKind.RPAREN,
        TokenKind.SEMI,
    }
)
EXPR_TERMINATORS = frozenset(
    {
        TokenKind.COLON,
        TokenKind.COMMA,
        TokenKind.EOF,
        TokenKind.FOR,
        TokenKind.MINUS,
        TokenKind.PERCENT,
        TokenKind.PLUS,
        TokenKind.RBRACKET,
        TokenKind.RPAREN,
        TokenKind.SLASH,
    }
)

# Augmented-assignment ops mapped to the corresponding plain binary op.
AUG_ASSIGN_OPS: dict[TokenKind, TokenKind] = {
    TokenKind.PLUS_EQUALS: TokenKind.PLUS,
    TokenKind.MINUS_EQUALS: TokenKind.MINUS,
    TokenKind.STAR_EQUALS: TokenKind.STAR,
    TokenKind.SLASH_EQUALS: TokenKind.SLASH,
    TokenKind.SLASH_SLASH_EQUALS: TokenKind.SLASH_SLASH,
    TokenKind.PERCENT_EQUALS: TokenKind.PERCENT,
    TokenKind.AMPERSAND_EQUALS: TokenKind.AMPERSAND,
    TokenKind.CARET_EQUALS: TokenKind.CARET,
    TokenKind.PIPE_EQUALS: TokenKind.PIPE,
    TokenKind.GREATER_GREATER_EQUALS: TokenKind.GREATER_GREATER,
    TokenKind.LESS_LESS_EQUALS: TokenKind.LESS_LESS,
}

# Highest precedence last. Matches Python operator precedence (and the Java
# reference's `operatorPrecedence`).
OPERATOR_PRECEDENCE: list[frozenset[TokenKind]] = [
    frozenset({TokenKind.OR}),
    frozenset({TokenKind.AND}),
    frozenset({TokenKind.NOT}),
    frozenset(
        {
            TokenKind.EQUALS_EQUALS,
            TokenKind.NOT_EQUALS,
            TokenKind.LESS,
            TokenKind.LESS_EQUALS,
            TokenKind.GREATER,
            TokenKind.GREATER_EQUALS,
            TokenKind.IN,
            TokenKind.NOT_IN,
        }
    ),
    frozenset({TokenKind.PIPE}),
    frozenset({TokenKind.CARET}),
    frozenset({TokenKind.AMPERSAND}),
    frozenset({TokenKind.GREATER_GREATER, TokenKind.LESS_LESS}),
    frozenset({TokenKind.MINUS, TokenKind.PLUS}),
    frozenset({TokenKind.SLASH, TokenKind.SLASH_SLASH, TokenKind.STAR, TokenKind.PERCENT}),
]

# Keywords that exist in the lexer but Starlark forbids: error on encounter.
FORBIDDEN_KEYWORDS: dict[TokenKind, str] = {
    TokenKind.AS: "'as' not supported",
    TokenKind.ASSERT: "'assert' not supported, use 'fail' instead",
    TokenKind.CLASS: "'class' not supported",
    TokenKind.DEL: "'del' not supported, use '.pop()' to delete an item",
    TokenKind.EXCEPT: "'except' not supported",
    TokenKind.FINALLY: "'finally' not supported",
    TokenKind.FROM: "'from' not supported",
    TokenKind.GLOBAL: "'global' not supported",
    TokenKind.IMPORT: "'import' not supported, use 'load' instead",
    TokenKind.IS: "'is' not supported, use '==' instead",
    TokenKind.NONLOCAL: "'nonlocal' not supported",
    TokenKind.RAISE: "'raise' not supported, use 'fail' instead",
    TokenKind.TRY: "'try' not supported, all exceptions are fatal",
    TokenKind.WITH: "'with' not supported",
    TokenKind.WHILE: "'while' not supported, use 'for' instead",
    TokenKind.YIELD: "'yield' not supported",
}


class Parser:
    """A single-shot parser. Produces a `StarlarkFile` plus accumulated errors."""

    __slots__ = ("_depth", "_errors", "_lexer", "_max_depth", "_max_errors", "_recovery", "_tok")

    def __init__(self, lexer: Lexer, max_depth: int = 256) -> None:
        self._lexer = lexer
        # Errors are shared with the lexer so the user gets one combined list.
        self._errors: list[StarlarkSyntaxError] = lexer.errors
        self._recovery = False
        self._max_errors = 100
        # Nesting depth, incremented on every recursive descent into
        # _parse_primary or _parse_suite. Caps at max_depth to convert a
        # would-be Python RecursionError into a clean SyntaxError.
        self._depth = 0
        self._max_depth = max_depth
        # Prime the first token.
        self._tok = self._fetch()

    def _enter(self) -> None:
        self._depth += 1
        if self._depth > self._max_depth:
            self._error(
                f"expression too deeply nested (>{self._max_depth} levels)",
                self._tok.start,
            )
            # Raise to abort parsing immediately; recursion would otherwise
            # blow Python's stack before the caller can react.
            raise StarlarkSyntaxException(self._errors)

    def _leave(self) -> None:
        self._depth -= 1

    # ---------------------------------------------------------------- token

    def _fetch(self) -> Token:
        tok = self._lexer.next_token()
        # Honor the forbidden-keyword set inline.
        msg = FORBIDDEN_KEYWORDS.get(tok.kind)
        if msg is not None:
            self._error(msg, tok.start)
        return tok

    def _next(self) -> Token:
        """Consume the current token; return the *previous* token."""
        prev = self._tok
        if self._tok.kind != TokenKind.EOF:
            self._tok = self._fetch()
        return prev

    def _expect(self, kind: TokenKind) -> Token:
        if self._tok.kind != kind:
            self._syntax_error(f"expected {kind}")
        return self._next()

    def _expect_and_recover(self, kind: TokenKind) -> Token:
        if self._tok.kind != kind:
            self._syntax_error(f"expected {kind}")
        else:
            self._recovery = False
        return self._next()

    def _at(self, kind: TokenKind) -> bool:
        return self._tok.kind == kind

    # ---------------------------------------------------------------- errors

    def _error(self, message: str, pos: int) -> None:
        if len(self._errors) >= self._max_errors:
            return
        self._errors.append(
            StarlarkSyntaxError(self._lexer.locs.position(pos), message)
        )

    def _syntax_error(self, message: str) -> None:
        if self._recovery:
            return
        if self._tok.kind == TokenKind.INDENT:
            self._error("indentation error", self._tok.start)
        else:
            tok_str = (
                f'"{self._tok.value}"'
                if self._tok.kind == TokenKind.STRING
                else (str(self._tok.value) if self._tok.value is not None else str(self._tok.kind))
            )
            self._error(f"syntax error at {tok_str!r}: {message}", self._tok.start)
        self._recovery = True

    def _sync_to(self, terminators: frozenset[TokenKind]) -> int:
        # Always include EOF to bound the loop.
        end = self._tok.end
        self._next()
        while self._tok.kind not in terminators and self._tok.kind != TokenKind.EOF:
            end = self._tok.end
            self._next()
        return end

    def _sync_past(self, terminators: frozenset[TokenKind]) -> int:
        while self._tok.kind not in terminators and self._tok.kind != TokenKind.EOF:
            self._next()
        end = self._tok.end
        self._next()
        return end

    def _make_error_expr(self, start: int, end: int) -> Identifier:
        # Mirror the Java reference: synthesize an Identifier so callers can
        # treat it like a regular expression.
        return Identifier(start=start, end=end, name="<error>")

    # ----------------------------------------------------------- entry points

    def parse_file(self, file: str = "<input>") -> StarlarkFile:
        # Each level of source nesting consumes ~12 Python frames in the
        # _parse_test → _parse_at_prec → ... → _parse_primary chain. To
        # let our own _max_depth (default 256) actually fire before
        # Python's RecursionError does, raise the recursion limit while
        # we parse and restore it afterwards.
        import sys
        old = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old, self._max_depth * 50 + 500))
        try:
            statements = self._parse_file_input()
        finally:
            sys.setrecursionlimit(old)
        return StarlarkFile(file=file, statements=statements, errors=self._errors)

    def parse_expression(self) -> Expression:
        import sys
        old = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old, self._max_depth * 50 + 500))
        try:
            e = self._parse_test_expr()
            # Skip any trailing NEWLINE that the lexer always inserts.
            while self._at(TokenKind.NEWLINE):
                self._next()
            self._expect(TokenKind.EOF)
        finally:
            sys.setrecursionlimit(old)
        return e

    # ----------------------------------------------------------- file_input

    def _parse_file_input(self) -> list[Statement]:
        stmts: list[Statement] = []
        while not self._at(TokenKind.EOF):
            if self._at(TokenKind.NEWLINE):
                self._expect_and_recover(TokenKind.NEWLINE)
            elif self._recovery:
                self._sync_to(STATEMENT_TERMINATORS)
                self._recovery = False
            else:
                self._parse_statement(stmts)
        return stmts

    # ----------------------------------------------------------- statements

    def _parse_statement(self, out: list[Statement]) -> None:
        if self._at(TokenKind.DEF):
            out.append(self._parse_def_statement())
        elif self._at(TokenKind.IF):
            out.append(self._parse_if_statement())
        elif self._at(TokenKind.FOR):
            out.append(self._parse_for_statement())
        else:
            self._parse_simple_statement(out)

    def _parse_simple_statement(self, out: list[Statement]) -> None:
        out.append(self._parse_small_statement())
        while self._at(TokenKind.SEMI):
            self._next()
            if self._at(TokenKind.NEWLINE) or self._at(TokenKind.EOF):
                break
            out.append(self._parse_small_statement())
        self._expect_and_recover(TokenKind.NEWLINE)

    def _parse_small_statement(self) -> Statement:
        if self._at(TokenKind.RETURN):
            return self._parse_return_statement()

        if self._tok.kind in (TokenKind.BREAK, TokenKind.CONTINUE, TokenKind.PASS):
            tok = self._next()
            return FlowStatement(start=tok.start, end=tok.end, kind=tok.kind)

        if self._at(TokenKind.LOAD):
            return self._parse_load_statement()

        lhs = self._parse_expr()

        op = AUG_ASSIGN_OPS.get(self._tok.kind)
        if self._at(TokenKind.EQUALS) or op is not None:
            self._next()
            rhs = self._parse_expr()
            return AssignmentStatement(
                start=lhs.start, end=rhs.end, lhs=lhs, op=op, rhs=rhs
            )

        return ExpressionStatement(start=lhs.start, end=lhs.end, expression=lhs)

    def _parse_return_statement(self) -> ReturnStatement:
        tok = self._expect(TokenKind.RETURN)
        if self._tok.kind in STATEMENT_TERMINATORS:
            return ReturnStatement(start=tok.start, end=tok.end, value=None)
        e = self._parse_expr()
        return ReturnStatement(start=tok.start, end=e.end, value=e)

    def _parse_load_statement(self) -> LoadStatement:
        load_tok = self._expect(TokenKind.LOAD)
        self._expect(TokenKind.LPAREN)
        if not self._at(TokenKind.STRING):
            module = StringLiteral(
                start=self._tok.start, end=self._tok.end, value=""
            )
            self._expect(TokenKind.STRING)
        else:
            module = self._parse_string_literal()

        if self._at(TokenKind.RPAREN):
            self._syntax_error("expected at least one symbol to load")
            tok = self._next()
            return LoadStatement(
                start=load_tok.start, end=tok.end, module=module, bindings=[]
            )
        self._expect(TokenKind.COMMA)

        bindings: list[LoadBinding] = []
        self._parse_load_symbol(bindings)
        while not self._at(TokenKind.RPAREN) and not self._at(TokenKind.EOF):
            self._expect(TokenKind.COMMA)
            if self._at(TokenKind.RPAREN):
                break
            self._parse_load_symbol(bindings)
        rparen = self._expect(TokenKind.RPAREN)
        return LoadStatement(
            start=load_tok.start, end=rparen.end, module=module, bindings=bindings
        )

    def _parse_load_symbol(self, out: list[LoadBinding]) -> None:
        tok = self._tok
        if tok.kind == TokenKind.STRING:
            name = tok.value
            local = Identifier(start=tok.start, end=tok.end, name=name)
            self._next()
            out.append(LoadBinding(local=local, original=local))
            return
        if tok.kind == TokenKind.IDENTIFIER:
            local = Identifier(start=tok.start, end=tok.end, name=tok.value)
            self._next()
            self._expect(TokenKind.EQUALS)
            if not self._at(TokenKind.STRING):
                self._syntax_error("expected string")
                return
            stok = self._next()
            original = Identifier(start=stok.start, end=stok.end, name=stok.value)
            out.append(LoadBinding(local=local, original=original))
            return
        self._syntax_error("expected either a literal string or an identifier")

    def _parse_if_statement(self) -> IfStatement:
        if_tok = self._expect(TokenKind.IF)
        cond = self._parse_test_expr()
        self._expect(TokenKind.COLON)
        body = self._parse_suite()
        root = IfStatement(start=if_tok.start, end=if_tok.end, cond=cond, body=body)
        tail = root
        while self._at(TokenKind.ELIF):
            elif_tok = self._expect(TokenKind.ELIF)
            cond = self._parse_test_expr()
            self._expect(TokenKind.COLON)
            body = self._parse_suite()
            elif_node = IfStatement(
                start=elif_tok.start, end=elif_tok.end, cond=cond, body=body
            )
            tail.else_block = [elif_node]
            tail = elif_node
        if self._at(TokenKind.ELSE):
            self._expect(TokenKind.ELSE)
            self._expect(TokenKind.COLON)
            tail.else_block = self._parse_suite()
        return root

    def _parse_for_statement(self) -> ForStatement:
        for_tok = self._expect(TokenKind.FOR)
        vars_ = self._parse_for_loop_vars()
        self._expect(TokenKind.IN)
        coll = self._parse_expr()
        self._expect(TokenKind.COLON)
        body = self._parse_suite()
        end = body[-1].end if body else coll.end
        return ForStatement(
            start=for_tok.start, end=end, vars=vars_, iterable=coll, body=body
        )

    def _parse_def_statement(self) -> DefStatement:
        def_tok = self._expect(TokenKind.DEF)
        name = self._parse_ident()
        self._expect(TokenKind.LPAREN)
        params = self._parse_parameters()
        self._expect(TokenKind.RPAREN)
        self._expect(TokenKind.COLON)
        body = self._parse_suite()
        end = body[-1].end if body else name.end
        return DefStatement(
            start=def_tok.start, end=end, name=name, parameters=params, body=body
        )

    def _parse_parameters(self) -> list[Parameter]:
        out: list[Parameter] = []
        seen = False
        while not self._at(TokenKind.RPAREN) and not self._at(TokenKind.COLON) and not self._at(
            TokenKind.EOF
        ):
            if seen:
                self._expect(TokenKind.COMMA)
                if self._at(TokenKind.RPAREN):
                    break
            out.append(self._parse_parameter())
            seen = True
        return out

    def _parse_parameter(self) -> Parameter:
        if self._at(TokenKind.STAR_STAR):
            tok = self._next()
            id_ = self._parse_ident()
            return StarStarParameter(start=tok.start, end=id_.end, name=id_)
        if self._at(TokenKind.STAR):
            tok = self._next()
            if self._at(TokenKind.IDENTIFIER):
                id_ = self._parse_ident()
                return StarParameter(start=tok.start, end=id_.end, name=id_)
            return StarParameter(start=tok.start, end=tok.end, name=None)
        id_ = self._parse_ident()
        if self._at(TokenKind.EQUALS):
            self._next()
            default = self._parse_test_expr()
            return OptionalParameter(
                start=id_.start, end=default.end, name=id_, default=default
            )
        return MandatoryParameter(start=id_.start, end=id_.end, name=id_)

    def _parse_suite(self) -> list[Statement]:
        self._enter()
        try:
            out: list[Statement] = []
            if self._at(TokenKind.NEWLINE):
                self._expect(TokenKind.NEWLINE)
                if not self._at(TokenKind.INDENT):
                    self._error("expected an indented block", self._tok.start)
                    return out
                self._expect(TokenKind.INDENT)
                while not self._at(TokenKind.OUTDENT) and not self._at(TokenKind.EOF):
                    self._parse_statement(out)
                self._expect_and_recover(TokenKind.OUTDENT)
            else:
                self._parse_simple_statement(out)
            return out
        finally:
            self._leave()

    # ----------------------------------------------------------- expressions

    def _parse_expr(self) -> Expression:
        e = self._parse_test_expr()
        if not self._at(TokenKind.COMMA):
            return e
        elements: list[Expression] = [e]
        self._parse_expr_list(elements, trailing_comma_allowed=False)
        return ListExpression(
            start=e.start, end=elements[-1].end, is_tuple=True, elements=elements
        )

    def _parse_expr_list(
        self, out: list[Expression], *, trailing_comma_allowed: bool
    ) -> None:
        while self._at(TokenKind.COMMA):
            self._next()
            if self._tok.kind in EXPR_LIST_TERMINATORS:
                if not trailing_comma_allowed:
                    self._error(
                        "trailing comma is allowed only in parenthesized tuples",
                        self._tok.start,
                    )
                break
            out.append(self._parse_test_expr())

    def _parse_test_expr(self) -> Expression:
        if self._at(TokenKind.LAMBDA):
            return self._parse_lambda(allow_cond=True)
        start = self._tok.start
        e = self._parse_at_prec(0)
        if self._at(TokenKind.IF):
            self._next()
            cond = self._parse_at_prec(0)
            if self._at(TokenKind.ELSE):
                self._next()
                else_expr = self._parse_test_expr()
                return ConditionalExpression(
                    start=e.start,
                    end=else_expr.end,
                    then_expr=e,
                    cond=cond,
                    else_expr=else_expr,
                )
            self._error(
                "missing else clause in conditional expression",
                start,
            )
        return e

    def _parse_test_no_cond(self) -> Expression:
        if self._at(TokenKind.LAMBDA):
            return self._parse_lambda(allow_cond=False)
        return self._parse_at_prec(0)

    def _parse_lambda(self, *, allow_cond: bool) -> LambdaExpression:
        tok = self._expect(TokenKind.LAMBDA)
        params = self._parse_parameters()
        self._expect(TokenKind.COLON)
        body = self._parse_test_expr() if allow_cond else self._parse_test_no_cond()
        return LambdaExpression(
            start=tok.start, end=body.end, parameters=params, body=body
        )

    def _parse_at_prec(self, prec: int) -> Expression:
        if prec >= len(OPERATOR_PRECEDENCE):
            return self._parse_primary_with_suffix()
        if self._at(TokenKind.NOT) and TokenKind.NOT in OPERATOR_PRECEDENCE[prec]:
            return self._parse_not_expr(prec)
        return self._parse_binop_expr(prec)

    def _parse_not_expr(self, prec: int) -> Expression:
        tok = self._expect(TokenKind.NOT)
        x = self._parse_at_prec(prec)
        return UnaryOperatorExpression(
            start=tok.start, end=x.end, op=TokenKind.NOT, operand=x
        )

    def _parse_binop_expr(self, prec: int) -> Expression:
        x = self._parse_at_prec(prec + 1)
        last_op: TokenKind | None = None
        while True:
            if self._at(TokenKind.NOT):
                # `not in` synthesis: NOT followed by IN at this precedence.
                self._next()
                if not self._at(TokenKind.IN):
                    self._syntax_error("expected 'in'")
                # Replace the current token's kind with NOT_IN.
                self._tok = Token(
                    kind=TokenKind.NOT_IN,
                    start=self._tok.start,
                    end=self._tok.end,
                    value=self._tok.value,
                )
            op = self._tok.kind
            if op not in OPERATOR_PRECEDENCE[prec]:
                return x
            if last_op is not None and TokenKind.EQUALS_EQUALS in OPERATOR_PRECEDENCE[prec]:
                self._error(
                    f"operator '{op}' is not associative with operator '{last_op}'; use parens",
                    self._tok.start,
                )
            self._next()
            y = self._parse_at_prec(prec + 1)
            x = self._optimize_binop(x, op, y)
            last_op = op

    def _optimize_binop(
        self, x: Expression, op: TokenKind, y: Expression
    ) -> Expression:
        # Constant-fold "a" + "b" — matches the Java reference's optimization.
        if (
            op == TokenKind.PLUS
            and isinstance(x, StringLiteral)
            and isinstance(y, StringLiteral)
        ):
            return StringLiteral(start=x.start, end=y.end, value=x.value + y.value)
        return BinaryOperatorExpression(
            start=x.start, end=y.end, op=op, lhs=x, rhs=y
        )

    # -------------------------------------------------------------- primary

    def _parse_primary(self) -> Expression:
        self._enter()
        try:
            return self._parse_primary_inner()
        finally:
            self._leave()

    def _parse_primary_inner(self) -> Expression:
        tok = self._tok
        kind = tok.kind
        if kind == TokenKind.INT:
            self._next()
            return IntLiteral(start=tok.start, end=tok.end, value=tok.value)
        if kind == TokenKind.FLOAT:
            self._next()
            return FloatLiteral(start=tok.start, end=tok.end, value=tok.value)
        if kind == TokenKind.STRING:
            return self._parse_string_literal()
        if kind == TokenKind.IDENTIFIER:
            return self._parse_ident()
        if kind == TokenKind.LBRACKET:
            return self._parse_list_maker()
        if kind == TokenKind.LBRACE:
            return self._parse_dict_expr()
        if kind == TokenKind.LPAREN:
            return self._parse_paren_or_tuple()
        if kind in (TokenKind.MINUS, TokenKind.PLUS, TokenKind.TILDE):
            self._next()
            x = self._parse_primary_with_suffix()
            return UnaryOperatorExpression(
                start=tok.start, end=x.end, op=kind, operand=x
            )
        # Error
        start = tok.start
        self._syntax_error("expected expression")
        end = self._sync_to(EXPR_TERMINATORS)
        return self._make_error_expr(start, end)

    def _parse_primary_with_suffix(self) -> Expression:
        e = self._parse_primary()
        while True:
            if self._at(TokenKind.DOT):
                e = self._parse_selector_suffix(e)
            elif self._at(TokenKind.LBRACKET):
                e = self._parse_slice_or_index_suffix(e)
            elif self._at(TokenKind.LPAREN):
                e = self._parse_call_suffix(e)
            else:
                return e

    def _parse_selector_suffix(self, e: Expression) -> Expression:
        self._expect(TokenKind.DOT)
        if self._at(TokenKind.IDENTIFIER):
            id_ = self._parse_ident()
            return DotExpression(start=e.start, end=id_.end, obj=e, name=id_)
        self._syntax_error("expected identifier after dot")
        end = self._sync_to(EXPR_TERMINATORS)
        return self._make_error_expr(e.start, end)

    def _parse_slice_or_index_suffix(self, e: Expression) -> Expression:
        self._expect(TokenKind.LBRACKET)
        start_e: Expression | None = None
        end_e: Expression | None = None
        step_e: Expression | None = None

        if not self._at(TokenKind.COLON):
            start_e = self._parse_expr()
            if self._at(TokenKind.RBRACKET):
                rbr = self._expect(TokenKind.RBRACKET)
                return IndexExpression(
                    start=e.start, end=rbr.end, obj=e, index=start_e
                )

        self._expect(TokenKind.COLON)
        if not self._at(TokenKind.COLON) and not self._at(TokenKind.RBRACKET):
            end_e = self._parse_test_expr()
        if self._at(TokenKind.COLON):
            self._next()
            if not self._at(TokenKind.RBRACKET):
                step_e = self._parse_test_expr()
        rbr = self._expect(TokenKind.RBRACKET)
        return SliceExpression(
            start=e.start,
            end=rbr.end,
            obj=e,
            start_index=start_e,
            end_index=end_e,
            step=step_e,
        )

    def _parse_call_suffix(self, fn: Expression) -> Expression:
        self._expect(TokenKind.LPAREN)
        args: list[Argument] = []
        if not self._at(TokenKind.RPAREN):
            self._parse_arguments(args)
        rparen = self._expect(TokenKind.RPAREN)
        return CallExpression(start=fn.start, end=rparen.end, fn=fn, args=args)

    def _parse_arguments(self, out: list[Argument]) -> None:
        seen = False
        while not self._at(TokenKind.RPAREN) and not self._at(TokenKind.EOF):
            if seen:
                if self._at(TokenKind.FOR):
                    self._syntax_error(
                        "Starlark does not support Python-style generator expressions"
                    )
                self._expect(TokenKind.COMMA)
                if self._at(TokenKind.RPAREN):
                    break
            out.append(self._parse_argument())
            seen = True

    def _parse_argument(self) -> Argument:
        if self._at(TokenKind.STAR_STAR):
            tok = self._next()
            v = self._parse_test_expr()
            return StarStarArgument(start=tok.start, end=v.end, value=v)
        if self._at(TokenKind.STAR):
            tok = self._next()
            v = self._parse_test_expr()
            return StarArgument(start=tok.start, end=v.end, value=v)
        e = self._parse_test_expr()
        if isinstance(e, Identifier) and self._at(TokenKind.EQUALS):
            self._next()
            v = self._parse_test_expr()
            return KeywordArgument(start=e.start, end=v.end, name=e, value=v)
        return PositionalArgument(start=e.start, end=e.end, value=e)

    def _parse_paren_or_tuple(self) -> Expression:
        lparen = self._expect(TokenKind.LPAREN)
        if self._at(TokenKind.RPAREN):
            rparen = self._next()
            return ListExpression(
                start=lparen.start, end=rparen.end, is_tuple=True, elements=[]
            )
        e = self._parse_test_expr()
        if self._at(TokenKind.RPAREN):
            self._next()
            return e
        if self._at(TokenKind.COMMA):
            elements = [e]
            self._parse_expr_list(elements, trailing_comma_allowed=True)
            rparen = self._expect(TokenKind.RPAREN)
            return ListExpression(
                start=lparen.start, end=rparen.end, is_tuple=True, elements=elements
            )
        if self._at(TokenKind.FOR):
            self._syntax_error(
                "Starlark does not support Python-style generator expressions"
            )
        self._expect(TokenKind.RPAREN)
        end = self._sync_to(EXPR_TERMINATORS)
        return self._make_error_expr(lparen.start, end)

    def _parse_list_maker(self) -> Expression:
        lbr = self._expect(TokenKind.LBRACKET)
        if self._at(TokenKind.RBRACKET):
            rbr = self._next()
            return ListExpression(
                start=lbr.start, end=rbr.end, is_tuple=False, elements=[]
            )
        e = self._parse_test_expr()
        if self._at(TokenKind.RBRACKET):
            rbr = self._next()
            return ListExpression(
                start=lbr.start, end=rbr.end, is_tuple=False, elements=[e]
            )
        if self._at(TokenKind.FOR):
            return self._parse_comprehension_suffix(lbr.start, e, TokenKind.RBRACKET)
        if self._at(TokenKind.COMMA):
            elements = [e]
            self._parse_expr_list(elements, trailing_comma_allowed=True)
            if self._at(TokenKind.RBRACKET):
                rbr = self._next()
                return ListExpression(
                    start=lbr.start, end=rbr.end, is_tuple=False, elements=elements
                )
            self._expect(TokenKind.RBRACKET)
            end = self._sync_past(LIST_TERMINATORS)
            return self._make_error_expr(lbr.start, end)
        self._syntax_error("expected ',', 'for' or ']'")
        end = self._sync_past(LIST_TERMINATORS)
        return self._make_error_expr(lbr.start, end)

    def _parse_dict_expr(self) -> Expression:
        lbr = self._expect(TokenKind.LBRACE)
        if self._at(TokenKind.RBRACE):
            rbr = self._next()
            return DictExpression(start=lbr.start, end=rbr.end, entries=[])
        first = self._parse_dict_entry()
        if self._at(TokenKind.FOR):
            return self._parse_comprehension_suffix(lbr.start, first, TokenKind.RBRACE)
        entries: list[DictEntry] = [first]
        if self._at(TokenKind.COMMA):
            self._next()
            self._parse_dict_entry_list(entries)
        if self._at(TokenKind.RBRACE):
            rbr = self._next()
            return DictExpression(start=lbr.start, end=rbr.end, entries=entries)
        self._expect(TokenKind.RBRACE)
        end = self._sync_past(DICT_TERMINATORS)
        return self._make_error_expr(lbr.start, end)

    def _parse_dict_entry_list(self, out: list[DictEntry]) -> None:
        while not self._at(TokenKind.RBRACE):
            out.append(self._parse_dict_entry())
            if self._at(TokenKind.COMMA):
                self._next()
            else:
                break

    def _parse_dict_entry(self) -> DictEntry:
        k = self._parse_test_expr()
        self._expect(TokenKind.COLON)
        v = self._parse_test_expr()
        return DictEntry(key=k, value=v)

    def _parse_for_loop_vars(self) -> Expression:
        e = self._parse_primary_with_suffix()
        if not self._at(TokenKind.COMMA):
            return e
        elements = [e]
        while self._at(TokenKind.COMMA):
            self._next()
            if self._tok.kind in EXPR_LIST_TERMINATORS:
                break
            elements.append(self._parse_primary_with_suffix())
        return ListExpression(
            start=e.start,
            end=elements[-1].end,
            is_tuple=True,
            elements=elements,
        )

    def _parse_comprehension_suffix(
        self, l_offset: int, body, closing: TokenKind
    ) -> Expression:
        clauses: list = []
        while True:
            if self._at(TokenKind.FOR):
                self._next()
                vars_ = self._parse_for_loop_vars()
                self._expect(TokenKind.IN)
                seq = self._parse_at_prec(0)
                clauses.append(ComprehensionClauseFor(vars=vars_, iterable=seq))
            elif self._at(TokenKind.IF):
                self._next()
                cond = self._parse_test_no_cond()
                clauses.append(ComprehensionClauseIf(cond=cond))
            elif self._at(closing):
                break
            else:
                self._syntax_error(f"expected '{closing}', 'for', or 'if'")
                end = self._sync_past(LIST_TERMINATORS)
                return self._make_error_expr(l_offset, end)
        rtok = self._expect(closing)
        is_dict = closing == TokenKind.RBRACE
        return Comprehension(
            start=l_offset,
            end=rtok.end,
            is_dict=is_dict,
            body=body,
            clauses=clauses,
        )

    def _parse_string_literal(self) -> StringLiteral:
        tok = self._expect(TokenKind.STRING)
        if self._at(TokenKind.STRING):
            self._error(
                "implicit string concatenation is forbidden, use the + operator",
                self._tok.start,
            )
        return StringLiteral(start=tok.start, end=tok.end, value=tok.value)

    def _parse_ident(self) -> Identifier:
        if not self._at(TokenKind.IDENTIFIER):
            start = self._tok.start
            end = self._expect(TokenKind.IDENTIFIER).end
            return self._make_error_expr(start, end)
        tok = self._next()
        return Identifier(start=tok.start, end=tok.end, name=tok.value)


# ---------------------------------------------------------------- public API


def parse(source: str, file: str = "<input>") -> StarlarkFile:
    """Parse `source` as a Starlark file. Errors are returned in the StarlarkFile."""
    lexer = Lexer(source, file=file)
    return Parser(lexer).parse_file(file=file)


def parse_expression(source: str, file: str = "<input>") -> Expression:
    """Parse `source` as a single Starlark expression. Raises if there are errors."""
    lexer = Lexer(source, file=file)
    p = Parser(lexer)
    e = p.parse_expression()
    if lexer.errors:
        raise ValueError("; ".join(str(err) for err in lexer.errors))
    return e


__all__ = ["Parser", "ast", "parse", "parse_expression"]
