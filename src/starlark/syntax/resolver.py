"""Static name resolution for Starlark.

Ported (in spirit, not in detail) from `net.starlark.java.syntax.Resolver`. Our
job is to:

1. Compute, for each function/lambda/comprehension scope, the set of names
   that are local to that scope. The evaluator uses these to allocate frame
   slots and to detect "referenced before assignment" at runtime.
2. Classify every Identifier read with one of: LOCAL, FREE, GLOBAL,
   PREDECLARED, UNIVERSAL — so the evaluator knows which environment to
   read from.
3. Catch a handful of static errors that the spec demands: `break` /
   `continue` outside a loop, `return` outside a function, duplicate
   parameter names, parameter ordering mistakes, assignment to None / True /
   False (which in Starlark are universal-scope identifiers, not literals).

We deliberately do NOT compute Java-style numeric frame indices. The
evaluator uses dicts keyed by name, which is plenty fast for our purposes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from . import ast
from .ast import (
    AssignmentStatement,
    BinaryOperatorExpression,
    CallExpression,
    Comprehension,
    ComprehensionClauseFor,
    ConditionalExpression,
    DefStatement,
    DictEntry,
    DictExpression,
    DotExpression,
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
    StringLiteral,
    UnaryOperatorExpression,
)
from .errors import SyntaxError as StarlarkSyntaxError
from .location import FileLocations
from .tokens import TokenKind


class Scope(Enum):
    LOCAL = "local"
    FREE = "free"
    GLOBAL = "global"
    PREDECLARED = "predeclared"
    UNIVERSAL = "universal"

    def __str__(self) -> str:
        return self.value


@dataclass(slots=True)
class Binding:
    """Resolution result attached to each Identifier read or write."""

    scope: Scope
    name: str


# Names that the spec reserves as universals; cannot be reassigned.
RESERVED_UNIVERSALS = frozenset({"None", "True", "False"})


class _Block:
    """One scope of name resolution.

    `kind` is one of "file", "function", "comprehension". `locals_` is the set
    of names bound *in this scope*. `parent` is the enclosing block.
    """

    __slots__ = ("kind", "locals_", "parent")

    def __init__(self, kind: str, parent: _Block | None) -> None:
        self.kind = kind
        self.locals_: set[str] = set()
        self.parent: _Block | None = parent


class Resolver:
    """Resolves names in a parsed `StarlarkFile`."""

    def __init__(
        self,
        file: StarlarkFile,
        predeclared: frozenset[str],
        universal: frozenset[str],
        locs: FileLocations,
    ) -> None:
        self.file = file
        self.predeclared = predeclared
        self.universal = universal
        self.locs = locs
        self.errors: list[StarlarkSyntaxError] = file.errors
        # Stack of enclosing blocks. The bottom is always the file block.
        self._blocks: list[_Block] = [_Block("file", None)]
        # Counters for `break` / `continue` / `return` validation.
        self._loop_depth = 0
        self._function_depth = 0

    # -------------------------------------------------------------- public API

    def resolve(self) -> None:
        # First pass: determine module-level globals so forward references work.
        for stmt in self.file.statements:
            self._declare_top_level(stmt)
        self.file.globals = sorted(self._blocks[0].locals_)

        # Second pass: walk each statement, resolving identifiers.
        for stmt in self.file.statements:
            self._resolve_stmt(stmt)

    # -------------------------------------------------------------- helpers

    def _error(self, msg: str, pos: int) -> None:
        self.errors.append(StarlarkSyntaxError(self.locs.position(pos), msg))

    def _is_in_function(self) -> bool:
        return self._function_depth > 0

    def _current_block(self) -> _Block:
        return self._blocks[-1]

    def _bind(self, name: str, pos: int) -> None:
        if name in RESERVED_UNIVERSALS:
            self._error(f"cannot reassign {name}", pos)
            return
        self._current_block().locals_.add(name)

    def _classify(self, name: str) -> Binding:
        # Walk from innermost to outermost. The first scope that binds the name wins.
        for block in reversed(self._blocks):
            if name in block.locals_:
                if block.kind == "file":
                    return Binding(Scope.GLOBAL, name)
                if block is self._current_block():
                    return Binding(Scope.LOCAL, name)
                return Binding(Scope.FREE, name)
        if name in self.predeclared:
            return Binding(Scope.PREDECLARED, name)
        if name in self.universal:
            return Binding(Scope.UNIVERSAL, name)
        # Unbound — the evaluator may report this at runtime, but it can also
        # happen due to forward references to top-level globals when we resolve
        # before fully populating the file scope. Treat as GLOBAL; runtime
        # NameError will surface if it really is unbound.
        return Binding(Scope.GLOBAL, name)

    # ----------------------------------------------------------- top-level pre-pass

    def _declare_top_level(self, stmt) -> None:
        """First pass: collect names bound at module scope."""
        if isinstance(stmt, AssignmentStatement) and stmt.op is None:
            self._collect_assign_names(stmt.lhs, into=self._blocks[0].locals_)
        elif isinstance(stmt, AssignmentStatement):
            # augmented assignment: also binds at module scope (read+write)
            self._collect_assign_names(stmt.lhs, into=self._blocks[0].locals_)
        elif isinstance(stmt, DefStatement):
            self._blocks[0].locals_.add(stmt.name.name)
        elif isinstance(stmt, ForStatement):
            self._collect_assign_names(stmt.vars, into=self._blocks[0].locals_)
            for s in stmt.body:
                self._declare_top_level(s)
        elif isinstance(stmt, IfStatement):
            for s in stmt.body:
                self._declare_top_level(s)
            for s in stmt.else_block:
                self._declare_top_level(s)
        elif isinstance(stmt, LoadStatement):
            for b in stmt.bindings:
                self._blocks[0].locals_.add(b.local.name)

    @staticmethod
    def _collect_assign_names(target, into: set[str]) -> None:
        """Walks an assignment LHS and adds bound names to `into`.

        Supports: Identifier, ListExpression (tuple or list, recursively).
        Index/dot/slice targets bind nothing new (they mutate an existing
        object) so we skip them.
        """
        if isinstance(target, Identifier):
            into.add(target.name)
        elif isinstance(target, ListExpression):
            for el in target.elements:
                Resolver._collect_assign_names(el, into)
        # IndexExpression, DotExpression, SliceExpression: bind nothing new.

    # ----------------------------------------------------------- statements

    def _resolve_stmt(self, stmt) -> None:
        if isinstance(stmt, AssignmentStatement):
            self._resolve_assign(stmt)
        elif isinstance(stmt, ExpressionStatement):
            self._resolve_expr(stmt.expression)
        elif isinstance(stmt, IfStatement):
            self._resolve_expr(stmt.cond)
            for s in stmt.body:
                self._resolve_stmt(s)
            for s in stmt.else_block:
                self._resolve_stmt(s)
        elif isinstance(stmt, ForStatement):
            self._resolve_expr(stmt.iterable)
            self._declare_assign_targets(stmt.vars)
            self._resolve_assign_target(stmt.vars)
            self._loop_depth += 1
            try:
                for s in stmt.body:
                    self._resolve_stmt(s)
            finally:
                self._loop_depth -= 1
        elif isinstance(stmt, DefStatement):
            self._resolve_def(stmt)
        elif isinstance(stmt, ReturnStatement):
            if not self._is_in_function():
                self._error("return statement outside of a function", stmt.start)
            if stmt.value is not None:
                self._resolve_expr(stmt.value)
        elif isinstance(stmt, FlowStatement):
            if stmt.kind in (TokenKind.BREAK, TokenKind.CONTINUE):
                if self._loop_depth == 0:
                    self._error(f"{stmt.kind} statement outside of a loop", stmt.start)
            # PASS: no-op
        elif isinstance(stmt, LoadStatement):
            # load() bindings are bound at module scope; we already declared them.
            for binding in stmt.bindings:
                binding.local.binding = Binding(Scope.GLOBAL, binding.local.name)
                # `original` is just a string-style key; we still classify it.
                binding.original.binding = Binding(Scope.GLOBAL, binding.original.name)
        else:
            raise AssertionError(f"unhandled statement {type(stmt).__name__}")

    def _resolve_assign(self, stmt: AssignmentStatement) -> None:
        self._resolve_expr(stmt.rhs)
        # For augmented assignment, the LHS is also read first.
        if stmt.op is not None:
            self._resolve_assign_target_for_read(stmt.lhs)
        self._declare_assign_targets(stmt.lhs)
        self._resolve_assign_target(stmt.lhs)

    def _declare_assign_targets(self, target) -> None:
        """Binds names found in an assignment LHS in the current block."""
        if isinstance(target, Identifier):
            if target.name in RESERVED_UNIVERSALS:
                self._error(f"cannot reassign {target.name}", target.start)
                return
            block = self._current_block()
            if block.kind == "file":
                # Already pre-declared.
                return
            block.locals_.add(target.name)
        elif isinstance(target, ListExpression):
            for el in target.elements:
                self._declare_assign_targets(el)
        # IndexExpression/DotExpression/SliceExpression mutate; nothing to bind.

    def _resolve_assign_target(self, target) -> None:
        """Resolve identifiers used as assignment targets.

        For a tuple/list target, recurse. For an index/dot/slice target, the
        receiver is read.
        """
        if isinstance(target, Identifier):
            target.binding = self._classify(target.name)
        elif isinstance(target, ListExpression):
            for el in target.elements:
                self._resolve_assign_target(el)
        elif isinstance(target, IndexExpression):
            self._resolve_expr(target.obj)
            self._resolve_expr(target.index)
        elif isinstance(target, DotExpression):
            self._resolve_expr(target.obj)
        elif isinstance(target, SliceExpression):
            self._resolve_expr(target.obj)
            if target.start_index is not None:
                self._resolve_expr(target.start_index)
            if target.end_index is not None:
                self._resolve_expr(target.end_index)
            if target.step is not None:
                self._resolve_expr(target.step)
        else:
            self._error(
                f"cannot assign to {type(target).__name__}", target.start
            )

    def _resolve_assign_target_for_read(self, target) -> None:
        """Resolve LHS as a *read* (used by augmented assignment)."""
        if isinstance(target, Identifier):
            target.binding = self._classify(target.name)
        elif isinstance(target, (IndexExpression, DotExpression, SliceExpression)):
            self._resolve_assign_target(target)
        else:
            self._error(
                f"cannot use {type(target).__name__} as augmented assignment target",
                target.start,
            )

    # ----------------------------------------------------------- def / lambda

    def _resolve_def(self, stmt: DefStatement) -> None:
        # The function name is bound in the enclosing block; that's already done
        # for top-level defs. For nested defs, we bind it in the current block.
        block = self._current_block()
        if block.kind != "file":
            block.locals_.add(stmt.name.name)
        stmt.name.binding = self._classify(stmt.name.name)

        self._validate_parameters(stmt.parameters)

        # Pre-scan the body for assignment targets to populate the function's
        # locals (Python-like semantics).
        func_block = _Block("function", self._current_block())
        # Parameters become locals immediately.
        for p in stmt.parameters:
            pname = _param_name(p)
            if pname is not None:
                func_block.locals_.add(pname)
        # Pre-scan body for assignments.
        for s in stmt.body:
            self._scan_locals(s, func_block.locals_)

        self._blocks.append(func_block)
        self._function_depth += 1
        prev_loop_depth = self._loop_depth
        self._loop_depth = 0  # break/continue do not cross function boundaries
        try:
            # Resolve parameter defaults in the *enclosing* scope. To do that,
            # we briefly pop the function block.
            self._blocks.pop()
            self._function_depth -= 1
            for p in stmt.parameters:
                if isinstance(p, OptionalParameter):
                    self._resolve_expr(p.default)
                # Identifier within parameter is bound; classify as LOCAL once
                # we re-enter the function scope (below).
            self._blocks.append(func_block)
            self._function_depth += 1
            # Resolve parameter identifiers as locals.
            for p in stmt.parameters:
                pname_id = _param_ident(p)
                if pname_id is not None:
                    pname_id.binding = Binding(Scope.LOCAL, pname_id.name)
            # Resolve body.
            for s in stmt.body:
                self._resolve_stmt(s)
        finally:
            self._loop_depth = prev_loop_depth
            self._function_depth -= 1
            self._blocks.pop()

        stmt.locals = sorted(func_block.locals_)
        # Free vars: identifiers in the body that resolved to FREE.
        stmt.freevars = sorted(_collect_freevars_for_function(stmt))

    def _resolve_lambda(self, expr: LambdaExpression) -> None:
        self._validate_parameters(expr.parameters)

        func_block = _Block("function", self._current_block())
        for p in expr.parameters:
            pname = _param_name(p)
            if pname is not None:
                func_block.locals_.add(pname)
        # Lambda body is a single expression; it can only "assign" via
        # comprehension/lambda nesting, but its locals are just the parameters.

        # Defaults resolve in the enclosing scope.
        for p in expr.parameters:
            if isinstance(p, OptionalParameter):
                self._resolve_expr(p.default)

        self._blocks.append(func_block)
        self._function_depth += 1
        prev_loop_depth = self._loop_depth
        self._loop_depth = 0
        try:
            for p in expr.parameters:
                pname_id = _param_ident(p)
                if pname_id is not None:
                    pname_id.binding = Binding(Scope.LOCAL, pname_id.name)
            self._resolve_expr(expr.body)
        finally:
            self._loop_depth = prev_loop_depth
            self._function_depth -= 1
            self._blocks.pop()

        expr.locals = sorted(func_block.locals_)
        expr.freevars = sorted(_collect_freevars_for_lambda(expr))

    def _validate_parameters(self, params: list[Parameter]) -> None:
        seen: dict[str, int] = {}
        seen_default = False
        seen_star = False
        seen_starstar = False
        for p in params:
            if isinstance(p, MandatoryParameter):
                if seen_default and not seen_star:
                    self._error(
                        "non-default parameter follows default parameter", p.start
                    )
                if seen_starstar:
                    self._error("parameter after **kwargs", p.start)
                self._check_param_name(p.name, seen, p.start)
            elif isinstance(p, OptionalParameter):
                seen_default = True
                if seen_starstar:
                    self._error("parameter after **kwargs", p.start)
                self._check_param_name(p.name, seen, p.start)
            elif isinstance(p, StarParameter):
                if seen_star:
                    self._error("multiple *args parameters", p.start)
                if seen_starstar:
                    self._error("*args after **kwargs", p.start)
                seen_star = True
                if p.name is not None:
                    self._check_param_name(p.name, seen, p.start)
            elif isinstance(p, StarStarParameter):
                if seen_starstar:
                    self._error("multiple **kwargs parameters", p.start)
                seen_starstar = True
                self._check_param_name(p.name, seen, p.start)

    def _check_param_name(self, ident: Identifier, seen: dict[str, int], pos: int) -> None:
        if ident.name in seen:
            self._error(f"duplicate parameter name: {ident.name}", pos)
        seen[ident.name] = pos

    def _scan_locals(self, stmt, into: set[str]) -> None:
        """Find names bound by `stmt` (recursing through control flow, but NOT
        into nested functions/lambdas/comprehensions, which have their own scopes)."""
        if isinstance(stmt, AssignmentStatement):
            self._collect_assign_names(stmt.lhs, into)
        elif isinstance(stmt, DefStatement):
            into.add(stmt.name.name)
        elif isinstance(stmt, ForStatement):
            self._collect_assign_names(stmt.vars, into)
            for s in stmt.body:
                self._scan_locals(s, into)
        elif isinstance(stmt, IfStatement):
            for s in stmt.body:
                self._scan_locals(s, into)
            for s in stmt.else_block:
                self._scan_locals(s, into)
        elif isinstance(stmt, LoadStatement):
            # load() at module scope only; skip.
            pass

    # ----------------------------------------------------------- expressions

    def _resolve_expr(self, expr) -> None:
        if isinstance(expr, Identifier):
            expr.binding = self._classify(expr.name)
        elif isinstance(expr, (IntLiteral, FloatLiteral, StringLiteral)):
            return
        elif isinstance(expr, UnaryOperatorExpression):
            self._resolve_expr(expr.operand)
        elif isinstance(expr, BinaryOperatorExpression):
            self._resolve_expr(expr.lhs)
            self._resolve_expr(expr.rhs)
        elif isinstance(expr, ConditionalExpression):
            self._resolve_expr(expr.then_expr)
            self._resolve_expr(expr.cond)
            self._resolve_expr(expr.else_expr)
        elif isinstance(expr, ListExpression):
            for el in expr.elements:
                self._resolve_expr(el)
        elif isinstance(expr, DictExpression):
            for entry in expr.entries:
                self._resolve_expr(entry.key)
                self._resolve_expr(entry.value)
        elif isinstance(expr, IndexExpression):
            self._resolve_expr(expr.obj)
            self._resolve_expr(expr.index)
        elif isinstance(expr, SliceExpression):
            self._resolve_expr(expr.obj)
            if expr.start_index is not None:
                self._resolve_expr(expr.start_index)
            if expr.end_index is not None:
                self._resolve_expr(expr.end_index)
            if expr.step is not None:
                self._resolve_expr(expr.step)
        elif isinstance(expr, DotExpression):
            self._resolve_expr(expr.obj)
            # `name` is not classified — it's just a field name.
        elif isinstance(expr, CallExpression):
            self._resolve_expr(expr.fn)
            seen_kw: dict[str, int] = {}
            for arg in expr.args:
                if isinstance(arg, PositionalArgument):
                    self._resolve_expr(arg.value)
                elif isinstance(arg, KeywordArgument):
                    if arg.name.name in seen_kw:
                        self._error(
                            f"duplicate keyword argument: {arg.name.name}", arg.start
                        )
                    seen_kw[arg.name.name] = arg.start
                    self._resolve_expr(arg.value)
                elif isinstance(arg, (StarArgument, StarStarArgument)):
                    self._resolve_expr(arg.value)
        elif isinstance(expr, LambdaExpression):
            self._resolve_lambda(expr)
        elif isinstance(expr, Comprehension):
            self._resolve_comprehension(expr)
        else:
            raise AssertionError(f"unhandled expression {type(expr).__name__}")

    def _resolve_comprehension(self, expr: Comprehension) -> None:
        # Per Python/Starlark, the iterable of the FIRST `for` clause is
        # evaluated in the enclosing scope. Subsequent clauses run in the
        # comprehension's own scope. Importantly, *every* comprehension-bound
        # name is statically local to the comprehension, even if a later
        # clause's iterable references it before its for-clause runs (that's
        # a `referenced before assignment` runtime error).
        if not expr.clauses or not isinstance(expr.clauses[0], ComprehensionClauseFor):
            return  # Parser already rejected; no-op.

        first = expr.clauses[0]
        self._resolve_expr(first.iterable)

        comp_block = _Block("comprehension", self._current_block())
        # Pre-declare all for-clause loop vars so name resolution within the
        # comprehension always classifies them as LOCAL.
        for clause in expr.clauses:
            if isinstance(clause, ComprehensionClauseFor):
                self._collect_assign_names(clause.vars, into=comp_block.locals_)

        self._blocks.append(comp_block)
        try:
            self._resolve_assign_target(first.vars)
            for clause in expr.clauses[1:]:
                if isinstance(clause, ComprehensionClauseFor):
                    self._resolve_expr(clause.iterable)
                    self._resolve_assign_target(clause.vars)
                else:
                    self._resolve_expr(clause.cond)
            if expr.is_dict:
                assert isinstance(expr.body, DictEntry)
                self._resolve_expr(expr.body.key)
                self._resolve_expr(expr.body.value)
            else:
                self._resolve_expr(expr.body)
        finally:
            self._blocks.pop()

        expr.locals = sorted(comp_block.locals_)


# --------------------------------------------------------------- helpers


def _param_name(p: Parameter) -> str | None:
    if isinstance(p, (MandatoryParameter, OptionalParameter, StarStarParameter)):
        return p.name.name
    if isinstance(p, StarParameter):
        return p.name.name if p.name is not None else None
    return None


def _param_ident(p: Parameter) -> Identifier | None:
    if isinstance(p, (MandatoryParameter, OptionalParameter, StarStarParameter)):
        return p.name
    if isinstance(p, StarParameter):
        return p.name
    return None


def _collect_freevars_for_function(stmt: DefStatement) -> set[str]:
    out: set[str] = set()
    locals_set = set(stmt.locals)
    for s in stmt.body:
        _collect_free_in_node(s, locals_set, out)
    return out


def _collect_freevars_for_lambda(expr: LambdaExpression) -> set[str]:
    out: set[str] = set()
    locals_set = set(expr.locals)
    _collect_free_in_node(expr.body, locals_set, out)
    return out


def _collect_free_in_node(node, locals_set: set[str], out: set[str]) -> None:
    """Walk a function body and collect names that resolved to FREE."""
    if isinstance(node, Identifier):
        if (
            node.binding is not None
            and isinstance(node.binding, Binding)
            and node.binding.scope == Scope.FREE
            and node.name not in locals_set
        ):
            out.add(node.name)
        return
    if isinstance(node, (IntLiteral, FloatLiteral, StringLiteral)):
        return
    if isinstance(node, (DefStatement, LambdaExpression)):
        # Names free in a nested function are also free in us, unless we bind them.
        for sub_free in node.freevars:
            if sub_free not in locals_set:
                out.add(sub_free)
        return
    # Otherwise, recurse generically over fields.
    for field_name in getattr(node, "__slots__", ()):
        val = getattr(node, field_name, None)
        if isinstance(val, list):
            for it in val:
                _collect_free_in_node(it, locals_set, out)
        elif hasattr(val, "__slots__") or isinstance(val, ast.Node):
            _collect_free_in_node(val, locals_set, out)
        elif val is not None and not isinstance(val, (str, int, float, bool, TokenKind)):
            try:
                _collect_free_in_node(val, locals_set, out)
            except Exception:
                pass


# --------------------------------------------------------------- public API


def resolve(
    file: StarlarkFile,
    locs: FileLocations,
    predeclared: frozenset[str] = frozenset(),
    universal: frozenset[str] = frozenset({"None", "True", "False"}),
) -> StarlarkFile:
    """Resolve names in `file`. Mutates the AST in place; returns the file."""
    Resolver(file, predeclared, universal, locs).resolve()
    return file


__all__ = ["Binding", "Resolver", "Scope", "resolve"]
