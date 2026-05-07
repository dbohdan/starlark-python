"""Compile-once `Program` API.

`compile(source)` parses (but does not resolve) the source and returns a
`Program`. The resulting object can be invoked many times with different
host-side environments via `.eval(...)` (for expressions) or `.exec(...)`
(for files). Each call gets a fresh `Module` and `Thread`; only the
parsed AST is reused.

This is the canonical entry point for hosts that apply the same script
to many inputs (e.g. data-transformation pipelines). Hosts that just
want one-shot evaluation can keep using `starlark.eval` /
`starlark.exec_file` — those are now thin wrappers over `compile`.

Resolution is intentionally redone on every call, because the resolver
walks the AST in place and consults the predeclared/universal name sets
that the host supplies at run time. The resolver is idempotent for our
purposes (it overwrites `Identifier.binding`, `DefStatement.locals`,
`StarlarkFile.globals`; never accumulates).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .eval.builtins import make_universal, with_mutability, with_thread
from .eval.evaluator import Frame, Thread, _eval_expr, eval_file
from .eval.module import Module
from .syntax import Lexer, Parser, resolve
from .syntax import ast as _ast
from .syntax.errors import StarlarkSyntaxException


class Program:
    """A parsed Starlark source ready to be run one or more times.

    Attributes:
        source: the original source string.
        filename: the filename the source was compiled from.
        is_expression: True if `source` is a single expression (use
            `.eval()`); False if it's a multi-statement file (use
            `.exec()`).
    """

    __slots__ = ("_expr", "_file", "_locs", "filename", "is_expression", "source")

    def __init__(
        self,
        source: str,
        filename: str,
        file: _ast.StarlarkFile,
        locs,
        expr: _ast.Expression | None,
    ) -> None:
        self.source = source
        self.filename = filename
        self._file = file
        self._locs = locs
        self._expr = expr
        self.is_expression = expr is not None

    # ----------------------------------------------------------- expression

    def eval(
        self,
        *,
        predeclared: dict[str, Any] | None = None,
        universal: dict[str, Any] | None = None,
        max_steps: int | None = None,
        on_max_steps: Callable[[Thread], None] | None = None,
        max_allocs: int | None = None,
        on_max_allocs: Callable[[Thread], None] | None = None,
        loader: Callable[[str], Module] | None = None,
        **env: Any,
    ) -> Any:
        """Evaluate as an expression. Returns the resulting value.

        `**env` extra kwargs are merged into the universal namespace
        (after `make_universal()` and the explicit `universal=` dict),
        matching the historical `starlark.eval()` shape.
        """
        if not self.is_expression:
            raise ValueError(
                "Program.eval(): source is a file, use .exec() instead "
                "(or compile a single expression)"
            )
        pre = predeclared or {}
        uni = make_universal()
        if universal:
            uni.update(universal)
        uni.update(env)
        _resolve(self._file, self._locs, pre, uni)
        module = Module(self.filename)
        thread = Thread(
            module=module,
            predeclared=pre,
            universal=uni,
            locs=self._locs,
            loader=loader,
            max_steps=max_steps,
            on_max_steps=on_max_steps,
            max_allocs=max_allocs,
            on_max_allocs=on_max_allocs,
        )
        frame = Frame(locals_=module.globals, function_name="<expr>", module=module)
        thread.frames.append(frame)
        try:
            with with_mutability(module.mutability), with_thread(thread):
                return _eval_expr(self._expr, frame, thread)
        finally:
            thread.frames.pop()

    # ----------------------------------------------------------- file

    def exec(
        self,
        *,
        predeclared: dict[str, Any] | None = None,
        universal: dict[str, Any] | None = None,
        max_steps: int | None = None,
        on_max_steps: Callable[[Thread], None] | None = None,
        max_allocs: int | None = None,
        on_max_allocs: Callable[[Thread], None] | None = None,
        loader: Callable[[str], Module] | None = None,
    ) -> Module:
        """Execute as a file. Returns the populated `Module`."""
        if self.is_expression:
            raise ValueError(
                "Program.exec(): source is a single expression, use .eval() instead"
            )
        pre = predeclared or {}
        uni = make_universal()
        if universal:
            uni.update(universal)
        _resolve(self._file, self._locs, pre, uni)
        module = Module(self.filename)
        thread = Thread(
            module=module,
            predeclared=pre,
            universal=uni,
            locs=self._locs,
            loader=loader,
            max_steps=max_steps,
            on_max_steps=on_max_steps,
            max_allocs=max_allocs,
            on_max_allocs=on_max_allocs,
        )
        with with_mutability(module.mutability), with_thread(thread):
            eval_file(self._file, thread)
        module.thread = thread
        return module


def _resolve(file: _ast.StarlarkFile, locs, pre: dict, uni: dict) -> None:
    """Resolve `file` against the given env. Raises on resolver errors.

    Clears any errors from a previous run on the same file before
    resolving, so repeat calls don't accumulate. The resolver mutates
    Identifier bindings and DefStatement metadata in place; those are
    overwritten cleanly.
    """
    file.errors = []
    resolve(file, locs, predeclared=frozenset(pre), universal=frozenset(uni))
    if file.errors:
        raise StarlarkSyntaxException(file.errors)


def compile(
    source: str,
    filename: str = "<input>",
    *,
    mode: str = "auto",
) -> Program:
    """Parse `source` into a reusable `Program`.

    `mode` is one of:

    - `"auto"` (default): try parsing as an expression first; on
      success, classify as an expression. Otherwise parse as a file.
      Convenient for hosts that accept either form (e.g. a transform
      that may be a one-liner expression or a multi-statement script).

    - `"expression"`: parse as a single expression. Use `.eval()` to run.

    - `"file"`: parse as a file (one or more statements). Use `.exec()`
      to run. This is what `starlark.exec_file()` uses internally — a
      single-line `do_something()` is a file with one expression
      statement, *not* an expression-mode Program.

    Raises `StarlarkSyntaxException` on lex or parse errors, or
    `ValueError` for an unrecognized `mode`.
    """
    if mode == "expression":
        return _compile_expression(source, filename)
    if mode == "file":
        return _compile_file(source, filename)
    if mode == "auto":
        try:
            return _compile_expression(source, filename)
        except StarlarkSyntaxException:
            return _compile_file(source, filename)
    raise ValueError(f"compile: unknown mode {mode!r}; expected 'auto', 'expression', or 'file'")


def _compile_expression(source: str, filename: str) -> Program:
    lexer = Lexer(source, file=filename)
    p = Parser(lexer)
    e = p.parse_expression()
    if lexer.errors:
        raise StarlarkSyntaxException(list(lexer.errors))
    # Wrap the expression in a StarlarkFile so the resolver and the
    # evaluator (which both work on files) can be reused.
    file = _ast.StarlarkFile(
        file=filename,
        statements=[_ast.ExpressionStatement(start=e.start, end=e.end, expression=e)],
        errors=[],
    )
    return Program(source, filename, file, lexer.locs, e)


def _compile_file(source: str, filename: str) -> Program:
    lexer = Lexer(source, file=filename)
    file = Parser(lexer).parse_file(file=filename)
    if file.errors:
        raise StarlarkSyntaxException(file.errors)
    return Program(source, filename, file, lexer.locs, None)


__all__ = ["Program", "compile"]
