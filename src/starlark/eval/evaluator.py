"""Tree-walking evaluator for Starlark.

Mirrors `net.starlark.java.eval.Eval` plus parts of `EvalUtils`. Performance
is not a goal; clarity is. We dispatch with isinstance checks and recursive
calls.

Internal control flow uses three Python exceptions:

- `_Break` — caught by enclosing `for`.
- `_Continue` — caught by enclosing `for` (continues the next iteration).
- `_Return(value)` — caught by the outermost frame of a function call.

`EvalError` is a *user-facing* exception, raised for any runtime semantic
error (bad type, division by zero, frozen mutation, etc.).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, TypeGuard

from ..syntax import ast
from ..syntax.location import FileLocations, Position
from ..syntax.resolver import Binding, Scope
from ..syntax.tokens import TokenKind
from .errors import AllocLimitExceeded, EvalError, StepLimitExceeded
from .function import StarlarkFunction, bind_arguments
from .limits import (
    check_container_size,
    check_repeat,
    string_alloc,
    tuple_alloc,
)
from .module import Module
from .mutability import Mutability
from .values import (
    BuiltinFunction,
    Dict,
    Range,
    StarlarkList,
    StarlarkSet,
    check_hashable,
    equal,
    less_than,
    repr_starlark,
    starlark_type,
    truth,
)

# Sentinel for "local declared but not assigned yet".
_UNBOUND = object()


# ---------------------------------------------------------------- signals


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class _Return(Exception):
    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        super().__init__()
        self.value = value


# ---------------------------------------------------------------- frame / thread


class Frame:
    """One call frame: a dict of locals plus a parent for closure capture."""

    __slots__ = ("function_name", "locals_", "module", "position")

    def __init__(
        self,
        locals_: dict[str, Any],
        function_name: str,
        module: Module,
        position: Position | None = None,
    ) -> None:
        self.locals_ = locals_
        self.function_name = function_name
        self.module = module
        self.position = position


class Thread:
    """Runtime state shared across one evaluation: module, builtins, call stack.

    Predeclared and universal envs are read-only dicts (host-supplied).

    Resource limits (all opt-in):

    - `max_steps`: cap on `steps`. When `tick()` would push `steps` over the
      limit, raises `StepLimitExceeded` (or invokes `on_max_steps` if the
      host supplied one).
    - `on_max_steps`: optional `Callable[[Thread], None]` invoked once when
      the step cap is reached. If it returns normally, `tick()` raises;
      hosts can use it to surface a richer error or to attribute the abort.
    - `max_allocs`: cap on `allocs` (cumulative bytes allocated, not
      live memory). When `add_allocs()` would push `allocs` over the limit,
      raises `AllocLimitExceeded` (or invokes `on_max_allocs`).
    - `on_max_allocs`: callback for the alloc cap, same shape as
      `on_max_steps`.

    Step accounting: `tick()` is called at three sites — top of every
    statement, top of every expression evaluation, and entry of every
    `call()` invocation. The unit is intentionally coarse (Starlark
    operations, not Python instructions) and matches starlark-java's
    documented choice. See `security/threat-model.md` and
    `security/cost-estimates.md`.

    Heap accounting: charge-only. Every container constructor and
    mutating concat/extend charges approximate bytes via `add_allocs`.
    The counter measures *cumulative allocation*, not live memory —
    values that go out of scope and are GC'd are not refunded. This
    makes the bound predictable but conservative.
    """

    __slots__ = (
        "active",
        "allocs",
        "depth",
        "frames",
        "loader",
        "locs",
        "max_allocs",
        "max_depth",
        "max_steps",
        "module",
        "on_max_allocs",
        "on_max_steps",
        "predeclared",
        "steps",
        "thread_local",
        "universal",
    )

    def __init__(
        self,
        module: Module,
        predeclared: Mapping[str, Any] | None = None,
        universal: Mapping[str, Any] | None = None,
        locs: FileLocations | None = None,
        loader=None,
        max_depth: int | None = None,
        max_steps: int | None = None,
        on_max_steps: Callable[[Thread], None] | None = None,
        max_allocs: int | None = None,
        on_max_allocs: Callable[[Thread], None] | None = None,
    ) -> None:
        self.module = module
        self.predeclared = predeclared or {}
        self.universal = universal or {}
        self.frames: list[Frame] = []
        self.locs = locs
        # Set of `id(ast_node)` currently executing — used to reject recursion
        # (Starlark spec: recursion is forbidden).
        self.active: set[int] = set()
        # Optional `Callable[[str], Module]` for resolving load() statements.
        self.loader = loader
        # AST-walk depth, incremented on entry to _eval_expr / _exec_stmt.
        # Capped to defuse stack-overflow on deeply nested values constructed
        # at runtime (e.g. `for i in range(N): x = [x]` with large N).
        from .limits import MAX_NESTING_DEPTH

        self.depth = 0
        self.max_depth = max_depth if max_depth is not None else MAX_NESTING_DEPTH
        # CPU-bound counter. `steps` is monotonic; `max_steps=None` disables
        # the cap. Hosts can read `steps` after evaluation to log the cost
        # of a configuration. Hot-path: tick() is on every statement/expr/call.
        self.steps: int = 0
        self.max_steps: int | None = max_steps
        self.on_max_steps: Callable[[Thread], None] | None = on_max_steps
        # Memory-bound counter. Charge-only (never refunded); semantically
        # cumulative bytes, not live memory. `add_allocs()` is hot — every
        # container construction and mutating concat charges it.
        self.allocs: int = 0
        self.max_allocs: int | None = max_allocs
        self.on_max_allocs: Callable[[Thread], None] | None = on_max_allocs
        # Host-attachable state, type-keyed (parallels Java's threadLocal).
        # Use `thread.thread_local[MyKey] = value` to stash per-evaluation
        # data; useful for builtins that want to share a cache or report
        # progress to the host.
        self.thread_local: dict[Any, Any] = {}

    def tick(self, n: int = 1) -> None:
        """Charge `n` Starlark operations against the step counter.

        When `max_steps` is set and the new total would exceed it, invokes
        `on_max_steps(self)` (if set) and then raises `StepLimitExceeded`.
        The callback is fired once per evaluation; subsequent ticks raise
        without re-firing it.
        """
        self.steps += n
        if self.max_steps is not None and self.steps > self.max_steps:
            cb = self.on_max_steps
            if cb is not None:
                # Clear before calling so re-entry doesn't re-fire.
                self.on_max_steps = None
                cb(self)
            raise StepLimitExceeded(
                f"Starlark computation cancelled: too many steps ({self.steps} > {self.max_steps})"
            )

    def add_allocs(self, n: int) -> None:
        """Charge `n` approximate bytes against the heap counter.

        When `max_allocs` is set and the new total would exceed it,
        invokes `on_max_allocs(self)` (if set) and then raises
        `AllocLimitExceeded`. The callback is fired once; subsequent
        calls raise without re-firing it.

        Negative deltas are rejected — the counter is charge-only by
        design, so refunds would silently desynchronize hosts that read
        `Thread.allocs` for cost reporting.
        """
        if n < 0:
            raise ValueError("add_allocs: negative delta is not supported")
        self.allocs += n
        if self.max_allocs is not None and self.allocs > self.max_allocs:
            cb = self.on_max_allocs
            if cb is not None:
                self.on_max_allocs = None
                cb(self)
            raise AllocLimitExceeded(
                f"Starlark computation cancelled: heap budget exhausted "
                f"({self.allocs} > {self.max_allocs} bytes)"
            )


# ---------------------------------------------------------------- entry


def eval_file(file: ast.StarlarkFile, thread: Thread) -> None:
    """Evaluate the top-level statements of a parsed file in `thread`."""
    # Top-level locals are the module globals dict directly.
    frame = Frame(
        locals_=thread.module.globals,
        function_name="<toplevel>",
        module=thread.module,
    )
    thread.frames.append(frame)
    try:
        for stmt in file.statements:
            _exec_stmt(stmt, frame, thread)
    finally:
        thread.frames.pop()


# ---------------------------------------------------------------- statements


def _exec_stmt(stmt, frame: Frame, thread: Thread) -> None:
    # Step accounting: one charge per statement. _Break/_Continue/_Return
    # are control-flow signals that re-enter the loop without going through
    # _exec_stmt, so they don't double-charge.
    thread.tick()
    if isinstance(stmt, ast.ExpressionStatement):
        _eval_expr(stmt.expression, frame, thread)
        return
    if isinstance(stmt, ast.AssignmentStatement):
        _exec_assign(stmt, frame, thread)
        return
    if isinstance(stmt, ast.IfStatement):
        cond = _eval_expr(stmt.cond, frame, thread)
        body = stmt.body if truth(cond) else stmt.else_block
        for s in body:
            _exec_stmt(s, frame, thread)
        return
    if isinstance(stmt, ast.ForStatement):
        iterable = _eval_expr(stmt.iterable, frame, thread)
        for item in _iterate(iterable):
            _assign_to_target(stmt.vars, item, frame, thread)
            try:
                for s in stmt.body:
                    _exec_stmt(s, frame, thread)
            except _Continue:
                continue
            except _Break:
                break
        return
    if isinstance(stmt, ast.DefStatement):
        fn = _make_function(stmt, frame, thread)
        _store_to_target(stmt.name, fn, frame, thread)
        return
    if isinstance(stmt, ast.ReturnStatement):
        val = _eval_expr(stmt.value, frame, thread) if stmt.value is not None else None
        raise _Return(val)
    if isinstance(stmt, ast.FlowStatement):
        if stmt.kind == TokenKind.BREAK:
            raise _Break()
        if stmt.kind == TokenKind.CONTINUE:
            raise _Continue()
        # PASS: no-op
        return
    if isinstance(stmt, ast.LoadStatement):
        from .loader import perform_load

        bindings = [(b.local.name, b.original.name) for b in stmt.bindings]
        results = perform_load(thread.loader, stmt.module.value, bindings)
        for k, v in results.items():
            thread.module.globals[k] = v
        return
    raise AssertionError(f"unhandled statement {type(stmt).__name__}")


def _exec_assign(stmt: ast.AssignmentStatement, frame: Frame, thread: Thread) -> None:
    if stmt.op is None:
        value = _eval_expr(stmt.rhs, frame, thread)
        _assign_to_target(stmt.lhs, value, frame, thread)
        return
    # Augmented: read LHS, combine, write back. Some ops mutate in place
    # rather than creating a new container — list `+=`, dict `|=`, and the
    # four set inplace operators (`|=`, `&=`, `-=`, `^=`).
    rhs = _eval_expr(stmt.rhs, frame, thread)
    current = _read_target(stmt.lhs, frame, thread)
    if isinstance(current, StarlarkList) and stmt.op == TokenKind.PLUS:
        current.extend(_iterate(rhs))
        return
    if (
        isinstance(current, StarlarkSet)
        and isinstance(rhs, StarlarkSet)
        and stmt.op
        in (
            TokenKind.PIPE,
            TokenKind.AMPERSAND,
            TokenKind.MINUS,
            TokenKind.CARET,
        )
    ):
        _set_inplace(current, rhs, stmt.op)
        return
    if isinstance(current, Dict) and isinstance(rhs, Dict) and stmt.op == TokenKind.PIPE:
        current.mutability.check("dict")
        for k, v in rhs.items():
            current[k] = v
        return
    new_value = _binop(stmt.op, current, rhs)
    _assign_to_target(stmt.lhs, new_value, frame, thread)


def _set_inplace(s: StarlarkSet, other: StarlarkSet, op: TokenKind) -> None:
    s.mutability.check("set")
    if op == TokenKind.PIPE:
        for x in other:
            s.add(x)
    elif op == TokenKind.AMPERSAND:
        keep = [x for x in s if x in other]
        s._data.clear()
        for x in keep:
            s._data[x] = None
    elif op == TokenKind.MINUS:
        for x in list(other):
            s.discard(x)
    elif op == TokenKind.CARET:
        in_other = list(other)
        keep = [x for x in s if x not in other]
        for x in in_other:
            if x not in s:
                keep.append(x)
        s._data.clear()
        for x in keep:
            s._data[x] = None


def _read_target(target, frame: Frame, thread: Thread) -> Any:
    """Read the current value at an assignment target (for augmented assignment)."""
    if isinstance(target, ast.Identifier):
        return _read_name(target, frame, thread)
    if isinstance(target, ast.IndexExpression):
        obj = _eval_expr(target.obj, frame, thread)
        idx = _eval_expr(target.index, frame, thread)
        return _index_get(obj, idx)
    if isinstance(target, ast.DotExpression):
        obj = _eval_expr(target.obj, frame, thread)
        return _attr_get(obj, target.name.name)
    raise EvalError(f"cannot read augmented assignment target {type(target).__name__}")


def _store_to_target(target: ast.Identifier, value: Any, frame: Frame, thread: Thread) -> None:
    """Bind a single Identifier target according to its resolved scope."""
    binding = target.binding
    if isinstance(binding, Binding):
        if binding.scope == Scope.LOCAL or binding.scope == Scope.FREE:
            frame.locals_[target.name] = value
            return
        if binding.scope == Scope.GLOBAL:
            thread.module.globals[target.name] = value
            return
    # No binding (could happen for synthesized error nodes); fall back to local.
    frame.locals_[target.name] = value


def _assign_to_target(target, value: Any, frame: Frame, thread: Thread) -> None:
    """Assign `value` into a generic LHS expression.

    Supports Identifier, ListExpression (tuple unpacking), IndexExpression,
    DotExpression, SliceExpression.
    """
    if isinstance(target, ast.Identifier):
        _store_to_target(target, value, frame, thread)
        return
    if isinstance(target, ast.ListExpression):
        n_targets = len(target.elements)
        try:
            items = list(_iterate(value))
        except EvalError:
            # Reframe as the assignment-side error wording, including the
            # arity hint the conformance tests check for.
            raise EvalError(
                f"got '{starlark_type(value)}' in sequence assignment "
                f"(want {n_targets}-element sequence)"
            ) from None
        if len(items) < n_targets:
            raise EvalError(f"too few values to unpack (got {len(items)}, want {n_targets})")
        if len(items) > n_targets:
            raise EvalError(f"too many values to unpack (got {len(items)}, want {n_targets})")
        for sub, v in zip(target.elements, items, strict=True):
            _assign_to_target(sub, v, frame, thread)
        return
    if isinstance(target, ast.IndexExpression):
        obj = _eval_expr(target.obj, frame, thread)
        idx = _eval_expr(target.index, frame, thread)
        _index_set(obj, idx, value)
        return
    if isinstance(target, ast.DotExpression):
        obj = _eval_expr(target.obj, frame, thread)
        _attr_set(obj, target.name.name, value)
        return
    raise EvalError(f"cannot assign to {type(target).__name__}")


# ---------------------------------------------------------------- expressions


def _eval_expr(expr, frame: Frame, thread: Thread) -> Any:
    # Step accounting: one charge per expression node visit. Sub-expressions
    # tick recursively, so `sum([i for i in range(N)])` charges O(N) rather
    # than O(1). Without this, a single huge expression would be one step.
    thread.tick()
    thread.depth += 1
    if thread.depth > thread.max_depth:
        thread.depth -= 1
        raise EvalError(f"expression too deeply nested (>{thread.max_depth} levels)")
    try:
        return _eval_expr_inner(expr, frame, thread)
    finally:
        thread.depth -= 1


def _eval_expr_inner(expr, frame: Frame, thread: Thread) -> Any:
    if isinstance(expr, ast.IntLiteral):
        return expr.value
    if isinstance(expr, ast.FloatLiteral):
        return expr.value
    if isinstance(expr, ast.StringLiteral):
        return expr.value
    if isinstance(expr, ast.Identifier):
        return _read_name(expr, frame, thread)
    if isinstance(expr, ast.UnaryOperatorExpression):
        return _unop(expr.op, _eval_expr(expr.operand, frame, thread))
    if isinstance(expr, ast.BinaryOperatorExpression):
        return _eval_binop(expr, frame, thread)
    if isinstance(expr, ast.ConditionalExpression):
        cond = _eval_expr(expr.cond, frame, thread)
        if truth(cond):
            return _eval_expr(expr.then_expr, frame, thread)
        return _eval_expr(expr.else_expr, frame, thread)
    if isinstance(expr, ast.ListExpression):
        items = [_eval_expr(e, frame, thread) for e in expr.elements]
        if expr.is_tuple:
            t = tuple(items)
            _charge_thread_alloc(tuple_alloc(len(t)))
            return t
        return StarlarkList(items, thread.module.mutability)
    if isinstance(expr, ast.DictExpression):
        d = Dict(mutability=thread.module.mutability)
        for entry in expr.entries:
            k = _eval_expr(entry.key, frame, thread)
            check_hashable(k)
            v = _eval_expr(entry.value, frame, thread)
            if k in d:
                raise EvalError(f"dictionary expression has duplicate key: {repr_starlark(k)}")
            d[k] = v
        return d
    if isinstance(expr, ast.IndexExpression):
        obj = _eval_expr(expr.obj, frame, thread)
        idx = _eval_expr(expr.index, frame, thread)
        return _index_get(obj, idx)
    if isinstance(expr, ast.SliceExpression):
        obj = _eval_expr(expr.obj, frame, thread)
        s = _eval_expr(expr.start_index, frame, thread) if expr.start_index else None
        e = _eval_expr(expr.end_index, frame, thread) if expr.end_index else None
        st = _eval_expr(expr.step, frame, thread) if expr.step else None
        return _slice(obj, s, e, st, thread.module.mutability)
    if isinstance(expr, ast.DotExpression):
        obj = _eval_expr(expr.obj, frame, thread)
        return _attr_get(obj, expr.name.name)
    if isinstance(expr, ast.CallExpression):
        return _eval_call(expr, frame, thread)
    if isinstance(expr, ast.LambdaExpression):
        return _make_lambda(expr, frame, thread)
    if isinstance(expr, ast.Comprehension):
        return _eval_comprehension(expr, frame, thread)
    raise AssertionError(f"unhandled expression {type(expr).__name__}")


def _read_name(ident: ast.Identifier, frame: Frame, thread: Thread) -> Any:
    binding = ident.binding
    name = ident.name
    if isinstance(binding, Binding):
        scope = binding.scope
        if scope == Scope.LOCAL:
            v = frame.locals_.get(name, _UNBOUND)
            if v is _UNBOUND:
                raise EvalError(f"local variable {name!r} is referenced before assignment")
            return v
        if scope == Scope.FREE:
            # Look in the closure dict.
            # Free variables in nested functions: the function carries its
            # closure; for comprehensions we just read from the parent frame.
            v = frame.locals_.get(name, _UNBOUND)
            if v is _UNBOUND:
                raise EvalError(f"free variable {name!r} referenced before assignment")
            return v
        if scope == Scope.GLOBAL:
            if name in thread.module.globals:
                return thread.module.globals[name]
            # Fall through to predeclared/universal as a fallback.
        if scope == Scope.PREDECLARED:
            if name in thread.predeclared:
                return thread.predeclared[name]
        if scope == Scope.UNIVERSAL:
            if name in thread.universal:
                return thread.universal[name]
            # Special-cased name-only universals
            if name == "None":
                return None
            if name == "True":
                return True
            if name == "False":
                return False
    # No binding info or fell through: do a scan.
    if name in frame.locals_:
        return frame.locals_[name]
    if name in thread.module.globals:
        return thread.module.globals[name]
    if name in thread.predeclared:
        return thread.predeclared[name]
    if name in thread.universal:
        return thread.universal[name]
    if name == "None":
        return None
    if name == "True":
        return True
    if name == "False":
        return False
    raise EvalError(f"name {name!r} is not defined")


def _eval_binop(expr: ast.BinaryOperatorExpression, frame: Frame, thread: Thread) -> Any:
    # Short-circuit logical operators.
    if expr.op == TokenKind.AND:
        left = _eval_expr(expr.lhs, frame, thread)
        return left if not truth(left) else _eval_expr(expr.rhs, frame, thread)
    if expr.op == TokenKind.OR:
        left = _eval_expr(expr.lhs, frame, thread)
        return left if truth(left) else _eval_expr(expr.rhs, frame, thread)
    a = _eval_expr(expr.lhs, frame, thread)
    b = _eval_expr(expr.rhs, frame, thread)
    return _binop(expr.op, a, b)


def _binop(op: TokenKind, a: Any, b: Any) -> Any:
    if op == TokenKind.PLUS:
        return _plus(a, b)
    if op == TokenKind.MINUS:
        return _minus(a, b)
    if op == TokenKind.STAR:
        return _multiply(a, b)
    if op == TokenKind.SLASH:
        return _div(a, b)
    if op == TokenKind.SLASH_SLASH:
        return _floordiv(a, b)
    if op == TokenKind.PERCENT:
        return _mod(a, b)
    if op == TokenKind.AMPERSAND:
        return _bitwise(op, a, b)
    if op == TokenKind.PIPE:
        return _bitwise(op, a, b)
    if op == TokenKind.CARET:
        return _bitwise(op, a, b)
    if op == TokenKind.LESS_LESS:
        return _shift_left(a, b)
    if op == TokenKind.GREATER_GREATER:
        return _shift_right(a, b)
    if op == TokenKind.EQUALS_EQUALS:
        return equal(a, b)
    if op == TokenKind.NOT_EQUALS:
        return not equal(a, b)
    if op == TokenKind.LESS:
        return less_than(a, b)
    if op == TokenKind.LESS_EQUALS:
        return not less_than(b, a)
    if op == TokenKind.GREATER:
        return less_than(b, a)
    if op == TokenKind.GREATER_EQUALS:
        return not less_than(a, b)
    if op == TokenKind.IN:
        return _contains(b, a)
    if op == TokenKind.NOT_IN:
        return not _contains(b, a)
    raise EvalError(f"unsupported binary operator {op}")


def _unop(op: TokenKind, x: Any) -> Any:
    if op == TokenKind.MINUS:
        if isinstance(x, bool):
            raise EvalError(f"unsupported unary operation: -{starlark_type(x)}")
        if isinstance(x, (int, float)):
            return -x
        raise EvalError(f"unsupported unary operator: -{starlark_type(x)}")
    if op == TokenKind.PLUS:
        if isinstance(x, bool):
            raise EvalError(f"unsupported unary operation: +{starlark_type(x)}")
        if isinstance(x, (int, float)):
            return +x
        raise EvalError(f"unsupported unary operator: +{starlark_type(x)}")
    if op == TokenKind.TILDE:
        if isinstance(x, bool) or not isinstance(x, int):
            raise EvalError(f"unsupported unary operation: ~{starlark_type(x)}")
        return ~x
    if op == TokenKind.NOT:
        return not truth(x)
    raise EvalError(f"unsupported unary operation: {op}")


# ---------------------------------------------------------------- arithmetic


def _is_int(v: Any) -> TypeGuard[int]:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> TypeGuard[int | float]:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _safe_num_op(op, a, b):
    """Run a numeric op, translating int-too-large overflow into a clean error."""
    try:
        return op(a, b)
    except OverflowError:
        raise EvalError("int too large to convert to float") from None


def _plus(a: Any, b: Any) -> Any:
    if _is_num(a) and _is_num(b):
        return _safe_num_op(lambda x, y: x + y, a, b)
    if isinstance(a, str) and isinstance(b, str):
        n = check_container_size(len(a) + len(b), label="characters")
        _charge_thread_alloc(string_alloc(n))
        return a + b
    if isinstance(a, tuple) and isinstance(b, tuple):
        n = check_container_size(len(a) + len(b))
        _charge_thread_alloc(tuple_alloc(n))
        return a + b
    if isinstance(a, StarlarkList) and isinstance(b, StarlarkList):
        # StarlarkList.__init__ already charges via _charge in values.py.
        check_container_size(len(a) + len(b))
        return StarlarkList(list(a) + list(b), a.mutability)
    raise EvalError(f"unsupported binary operation: {starlark_type(a)} + {starlark_type(b)}")


def _charge_thread_alloc(n: int) -> None:
    """Charge approximate bytes against the current Thread's heap counter.

    Mirrors `values._charge` but lives here to avoid pulling in builtins.py
    on every binary op. Both helpers do the same thing; either is fine.
    """
    from .builtins import _CURRENT_THREAD

    thread = _CURRENT_THREAD.get(None)
    if thread is not None:
        thread.add_allocs(n)


def _minus(a: Any, b: Any) -> Any:
    if _is_num(a) and _is_num(b):
        return _safe_num_op(lambda x, y: x - y, a, b)
    if isinstance(a, StarlarkSet) and isinstance(b, StarlarkSet):
        out = StarlarkSet(mutability=a.mutability)
        for x in a:
            if x not in b:
                out._data[x] = None
        return out
    raise EvalError(f"unsupported binary operation: {starlark_type(a)} - {starlark_type(b)}")


def _multiply(a: Any, b: Any) -> Any:
    if _is_num(a) and _is_num(b):
        return _safe_num_op(lambda x, y: x * y, a, b)
    if _is_int(a) and isinstance(b, str):
        check_repeat(max(0, a), len(b), unit="characters")
        out = b * max(0, a)
        _charge_thread_alloc(string_alloc(len(out)))
        return out
    if isinstance(a, str) and _is_int(b):
        check_repeat(max(0, b), len(a), unit="characters")
        out = a * max(0, b)
        _charge_thread_alloc(string_alloc(len(out)))
        return out
    if _is_int(a) and isinstance(b, tuple):
        check_repeat(max(0, a), len(b))
        out_t = b * max(0, a)
        _charge_thread_alloc(tuple_alloc(len(out_t)))
        return out_t
    if isinstance(a, tuple) and _is_int(b):
        check_repeat(max(0, b), len(a))
        out_t = a * max(0, b)
        _charge_thread_alloc(tuple_alloc(len(out_t)))
        return out_t
    if _is_int(a) and isinstance(b, StarlarkList):
        check_repeat(max(0, a), len(b))
        # StarlarkList.__init__ charges; no extra accounting here.
        return StarlarkList(list(b) * max(0, a), b.mutability)
    if isinstance(a, StarlarkList) and _is_int(b):
        check_repeat(max(0, b), len(a))
        return StarlarkList(list(a) * max(0, b), a.mutability)
    raise EvalError(f"unsupported binary operation: {starlark_type(a)} * {starlark_type(b)}")


def _div(a: Any, b: Any) -> Any:
    if _is_num(a) and _is_num(b):
        if b == 0:
            kind = "floating-point" if isinstance(a, float) or isinstance(b, float) else "integer"
            raise EvalError(f"{kind} division by zero")
        try:
            return float(a) / float(b)
        except OverflowError:
            raise EvalError("int too large to convert to float") from None
    raise EvalError(f"unsupported binary operation: {starlark_type(a)} / {starlark_type(b)}")


def _floordiv(a: Any, b: Any) -> Any:
    if _is_num(a) and _is_num(b):
        if b == 0:
            # Floor division always reports "integer division by zero",
            # regardless of the operand types — see conformance/float.star.
            raise EvalError("integer division by zero")
        # Special case: dividing by ±infinity. Python's `//` returns -1.0 for
        # `1.0 // -inf`; the Starlark spec wants -0.0 (the floor of the
        # mathematical quotient). Handle it explicitly.
        if isinstance(b, float) and (b == float("inf") or b == float("-inf")):
            # 1/inf -> 0.0; 1/-inf -> -0.0; sign follows a*sign(b).
            return 0.0 if (a > 0) == (b > 0) else -0.0
        try:
            return a // b
        except OverflowError:
            raise EvalError("int too large to convert to float") from None
    raise EvalError(f"unsupported binary operation: {starlark_type(a)} // {starlark_type(b)}")


def _mod(a: Any, b: Any) -> Any:
    if _is_num(a) and _is_num(b):
        if b == 0:
            kind = "floating-point" if isinstance(a, float) or isinstance(b, float) else "integer"
            raise EvalError(f"{kind} modulo by zero")
        return _safe_num_op(lambda x, y: x % y, a, b)
    if isinstance(a, str):
        return _str_format(a, b)
    raise EvalError(f"unsupported binary operation: {starlark_type(a)} %% {starlark_type(b)}")


def _bitwise(op: TokenKind, a: Any, b: Any) -> Any:
    if _is_int(a) and _is_int(b):
        if op == TokenKind.AMPERSAND:
            return a & b
        if op == TokenKind.PIPE:
            return a | b
        if op == TokenKind.CARET:
            return a ^ b
    if isinstance(a, Dict) and isinstance(b, Dict) and op == TokenKind.PIPE:
        # dict | dict: right-biased merge, like Python 3.9+.
        out = Dict(mutability=a.mutability)
        for k, v in a.items():
            out[k] = v
        for k, v in b.items():
            out[k] = v
        return out
    if isinstance(a, StarlarkSet) and isinstance(b, StarlarkSet):
        if op == TokenKind.AMPERSAND:
            return _set_op(a, b, lambda x, y: x in y)
        if op == TokenKind.PIPE:
            out = StarlarkSet(list(a), a.mutability)
            for x in b:
                out._data[x] = None
            return out
        if op == TokenKind.CARET:
            out = StarlarkSet(mutability=a.mutability)
            for x in a:
                if x not in b:
                    out._data[x] = None
            for x in b:
                if x not in a:
                    out._data[x] = None
            return out
    raise EvalError(
        f"unsupported binary operation: {starlark_type(a)} {_op_symbol(op)} {starlark_type(b)}"
    )


def _op_symbol(op: TokenKind) -> str:
    return {
        TokenKind.AMPERSAND: "&",
        TokenKind.PIPE: "|",
        TokenKind.CARET: "^",
    }.get(op, str(op))


def _set_op(a: StarlarkSet, b: StarlarkSet, keep) -> StarlarkSet:
    out = StarlarkSet(mutability=a.mutability)
    for x in a:
        if keep(x, b):
            out._data[x] = None
    return out


_SHIFT_LIMIT = 512  # bytes; matches the Java reference's cap (`1 << 512` is OK,
# `1 << 513` is rejected; the conformance suite tests at 520)


def _shift_left(a: Any, b: Any) -> Any:
    if _is_int(a) and _is_int(b):
        if b < 0:
            raise EvalError(f"negative shift count: {b}")
        if b > _SHIFT_LIMIT:
            raise EvalError(f"shift count too large: {b}")
        return a << b
    raise EvalError(f"unsupported binary operation: {starlark_type(a)} << {starlark_type(b)}")


def _shift_right(a: Any, b: Any) -> Any:
    if _is_int(a) and _is_int(b):
        if b < 0:
            raise EvalError(f"negative shift count: {b}")
        # Right shift can never blow up memory; cap left shift only.
        return a >> b
    raise EvalError(f"unsupported binary operation: {starlark_type(a)} >> {starlark_type(b)}")


def _contains(container: Any, item: Any, _depth: int = 0) -> bool:
    if isinstance(container, str):
        if not isinstance(item, str):
            raise EvalError(
                f"'in <string>' requires string as left operand, not {starlark_type(item)}"
            )
        return item in container
    if isinstance(container, (StarlarkList, tuple)):
        # Looking inside the container is one structural level; pass _depth so a
        # deeply nested item (`x in [x]`) trips MAX_NESTING_DEPTH in equal()
        # instead of leaking a RecursionError.
        return any(equal(x, item, _depth + 1) for x in container)
    if isinstance(container, Dict):
        return item in container
    if isinstance(container, StarlarkSet):
        return item in container
    if isinstance(container, Range):
        return item in container
    raise EvalError(f"unsupported 'in' operation on {starlark_type(container)}")


# ---------------------------------------------------------------- index / slice


def _index_get(obj: Any, idx: Any) -> Any:
    if isinstance(obj, str):
        if not _is_int(idx):
            raise EvalError(f"got {starlark_type(idx)} for string index, want int")
        n = len(obj)
        i = idx + n if idx < 0 else idx
        if i < 0 or i >= n:
            raise EvalError(f"index out of range (index is {idx}, but sequence has {n} elements)")
        return obj[i]
    if isinstance(obj, (StarlarkList, tuple)):
        if not _is_int(idx):
            raise EvalError(f"got {starlark_type(idx)} for sequence index, want int")
        n = len(obj)
        i = idx + n if idx < 0 else idx
        if i < 0 or i >= n:
            raise EvalError(f"index out of range (index is {idx}, but sequence has {n} elements)")
        return obj[i]
    if isinstance(obj, Dict):
        return obj[idx]
    if isinstance(obj, Range):
        if not _is_int(idx):
            raise EvalError(f"got {starlark_type(idx)} for sequence index, want int")
        return obj[idx]
    raise EvalError(f"type '{starlark_type(obj)}' has no operator []")


def _index_set(obj: Any, idx: Any, value: Any) -> None:
    if isinstance(obj, StarlarkList):
        if not _is_int(idx):
            raise EvalError(f"list index must be int, got {starlark_type(idx)}")
        n = len(obj)
        i = idx + n if idx < 0 else idx
        if i < 0 or i >= n:
            raise EvalError(f"index out of range (index is {idx}, but sequence has {n} elements)")
        obj[i] = value
        return
    if isinstance(obj, Dict):
        check_hashable(idx)
        obj[idx] = value
        return
    raise EvalError(f"unsupported indexed assignment on {starlark_type(obj)}")


def _slice(obj: Any, start, end, step, mutability: Mutability) -> Any:
    if step is None:
        step = 1
    if not _is_int(step):
        raise EvalError(f"slice step must be int, got {starlark_type(step)}")
    if step == 0:
        raise EvalError("slice step cannot be zero")
    for label, val in (("start", start), ("stop", end)):
        if val is not None and not _is_int(val):
            raise EvalError(f"got {starlark_type(val)} for {label} index, want int")
    if isinstance(obj, str):
        return obj[_py_slice(start, end, step)]
    if isinstance(obj, tuple):
        return obj[_py_slice(start, end, step)]
    if isinstance(obj, StarlarkList):
        return StarlarkList(list(obj)[_py_slice(start, end, step)], mutability)
    if isinstance(obj, Range):
        # Range slicing: produce a Range where possible.
        n = len(obj)
        s, e, st = _slice_indices(n, start, end, step)
        return Range(obj.start + s * obj.step, obj.start + e * obj.step, obj.step * st)
    raise EvalError(f"unsupported slicing on {starlark_type(obj)}")


def _py_slice(start, end, step):
    return slice(start, end, step)


def _slice_indices(n: int, start, end, step):
    s, e, st = slice(start, end, step).indices(n)
    return s, e, st


# ---------------------------------------------------------------- attr / call


def _attr_get(obj: Any, name: str) -> Any:
    # Structs (from the test driver) expose their fields via `.`.
    fields = getattr(obj, "fields", None)
    if isinstance(fields, dict) and name in fields:
        return fields[name]
    from . import methods

    method = methods.get_method(obj, name)
    if method is None:
        raise EvalError(f"'{starlark_type(obj)}' value has no field or method '{name}'")
    return method


def _attr_set(obj: Any, name: str, value: Any) -> None:
    # Mutable structs allow field assignment.
    fields = getattr(obj, "fields", None)
    frozen = getattr(obj, "_frozen", True)
    if isinstance(fields, dict) and not frozen:
        fields[name] = value
        return
    raise EvalError(f"{starlark_type(obj)} value does not support field assignment")


def _eval_call(expr: ast.CallExpression, frame: Frame, thread: Thread) -> Any:
    fn = _eval_expr(expr.fn, frame, thread)
    positional: list = []
    keyword: dict[str, Any] = {}
    for arg in expr.args:
        if isinstance(arg, ast.PositionalArgument):
            positional.append(_eval_expr(arg.value, frame, thread))
        elif isinstance(arg, ast.KeywordArgument):
            keyword[arg.name.name] = _eval_expr(arg.value, frame, thread)
        elif isinstance(arg, ast.StarArgument):
            v = _eval_expr(arg.value, frame, thread)
            positional.extend(_iterate(v))
        elif isinstance(arg, ast.StarStarArgument):
            v = _eval_expr(arg.value, frame, thread)
            if isinstance(v, Dict):
                items = list(v.items())
            elif isinstance(v, dict):
                items = list(v.items())
            else:
                raise EvalError(f"argument after ** must be dict, not {starlark_type(v)}")
            for k, val in items:
                if not isinstance(k, str):
                    raise EvalError("**kwargs keys must be strings")
                if k in keyword:
                    raise EvalError(f"duplicate keyword argument: {k!r}")
                keyword[k] = val
    return call(fn, positional, keyword, thread, position=_pos(expr.start, thread))


def call(
    fn: Any,
    positional: list,
    keyword: dict,
    thread: Thread,
    position: Position | None = None,
) -> Any:
    """Call a Starlark callable. Used by builtins too."""
    # Charge one step per call. This also catches builtin->user callbacks
    # like `sorted(key=fn)`, which otherwise wouldn't trigger an
    # _eval_expr tick for the inner call.
    thread.tick()
    if isinstance(fn, BuiltinFunction):
        try:
            return fn.impl(*positional, **keyword)
        except EvalError as e:
            # ResourceLimitExceeded/StepLimitExceeded/AllocLimitExceeded all
            # subclass EvalError, so this arm preserves them unchanged — they
            # must reach the host as the limit signal they are.
            e.push_frame(fn.name, position)
            raise
        except TypeError as e:
            # Translate Python's argument-binding TypeError into something
            # closer to the Java reference's wording. The raw message looks
            # like `d_pop() missing 1 required positional argument: 'key'`;
            # we strip the implementation-detail prefix and the quotes.
            msg = str(e)
            if "() " in msg:
                msg = msg.split("() ", 1)[1]
            msg = msg.replace("'", "")
            raise EvalError(msg) from None
        except MemoryError:
            # A genuine host out-of-memory condition, not a Starlark semantic
            # error. The in-band resource limits (step/alloc counters, the
            # container and integer caps) are what bound Starlark-induced
            # growth; a MemoryError that slips past them means the host itself
            # is exhausted. Let it propagate so the host sees the real
            # condition rather than a disguised EvalError it might retry.
            raise
        except Exception as e:
            # Safety net for unknown-unknowns: any other Python exception a
            # builtin raises (ValueError, KeyError, RecursionError, ...) would
            # otherwise escape raw and break the documented `except EvalError`
            # host contract. Normalize it. Specific normalizations elsewhere
            # (chr range, oversized-int stringification) still run first, so
            # this only catches what nothing else anticipated.
            err = EvalError(f"{type(e).__name__}: {e}" if str(e) else type(e).__name__)
            err.push_frame(fn.name, position)
            raise err from e
    if isinstance(fn, StarlarkFunction):
        # Recursion check: based on the *syntactic* identity of the def/lambda
        # AST node, not the StarlarkFunction value, so two closures created
        # from the same lambda still count as the same function (matches the
        # Java reference's Y-combinator-rejection behavior).
        node_id = id(fn.ast_node) if fn.ast_node is not None else id(fn)
        if node_id in thread.active:
            raise EvalError(f"function '{fn.name}' called recursively")
        locals_ = bind_arguments(fn, positional, keyword)
        # Pull in free variables from closure.
        for name in fn.freevars:
            if name in fn.closure:
                src = fn.closure[name]
                if name in src:
                    locals_[name] = src[name]
        new_frame = Frame(
            locals_=locals_,
            function_name=fn.name,
            module=thread.module,
            position=position,
        )
        thread.frames.append(new_frame)
        thread.active.add(node_id)
        try:
            if fn.body_expr is not None:
                return _eval_expr(fn.body_expr, new_frame, thread)
            try:
                for stmt in fn.body_stmts or ():
                    _exec_stmt(stmt, new_frame, thread)
            except _Return as r:
                return r.value
            return None
        except EvalError as e:
            e.push_frame(fn.name, position)
            raise
        finally:
            thread.active.discard(node_id)
            thread.frames.pop()
    raise EvalError(f"'{starlark_type(fn)}' object is not callable")


def _pos(offset: int, thread: Thread) -> Position | None:
    if thread.locs is None:
        return None
    return thread.locs.position(offset)


# ---------------------------------------------------------------- functions / lambdas


def _make_function(stmt: ast.DefStatement, frame: Frame, thread: Thread) -> StarlarkFunction:
    defaults: dict[str, Any] = {}
    for p in stmt.parameters:
        if isinstance(p, ast.OptionalParameter):
            defaults[p.name.name] = _eval_expr(p.default, frame, thread)
    closure: dict[str, dict] = {}
    for name in stmt.freevars:
        closure[name] = frame.locals_
    return StarlarkFunction(
        name=stmt.name.name,
        params=stmt.parameters,
        body_stmts=stmt.body,
        body_expr=None,
        defaults=defaults,
        closure=closure,
        position=_pos(stmt.start, thread),
        locals=tuple(stmt.locals),
        freevars=tuple(stmt.freevars),
        ast_node=stmt,
    )


def _make_lambda(expr: ast.LambdaExpression, frame: Frame, thread: Thread) -> StarlarkFunction:
    defaults: dict[str, Any] = {}
    for p in expr.parameters:
        if isinstance(p, ast.OptionalParameter):
            defaults[p.name.name] = _eval_expr(p.default, frame, thread)
    closure: dict[str, dict] = {}
    for name in expr.freevars:
        closure[name] = frame.locals_
    return StarlarkFunction(
        name="lambda",
        params=expr.parameters,
        body_stmts=None,
        body_expr=expr.body,
        defaults=defaults,
        closure=closure,
        position=_pos(expr.start, thread),
        locals=tuple(expr.locals),
        freevars=tuple(expr.freevars),
        ast_node=expr,
    )


# ---------------------------------------------------------------- comprehensions


def _eval_comprehension(expr: ast.Comprehension, frame: Frame, thread: Thread) -> Any:
    """Evaluate a list or dict comprehension.

    Comprehension variables live in the current frame for simplicity (the
    spec says they're scoped to the comprehension; in practice that's only
    visible if the same name shadows a function-level local, which is
    legal but rare). Save and restore those slots.
    """
    if expr.is_dict:
        result: Any = Dict(mutability=thread.module.mutability)
    else:
        result = StarlarkList([], thread.module.mutability)

    saved: dict[str, Any] = {}
    comp_locals = list(expr.locals)
    for name in comp_locals:
        if name in frame.locals_:
            saved[name] = frame.locals_[name]

    try:
        _eval_clauses(expr, expr.clauses, 0, frame, thread, result)
    finally:
        # Remove any names introduced by the comprehension; restore shadowed.
        for name in comp_locals:
            if name in saved:
                frame.locals_[name] = saved[name]
            else:
                frame.locals_.pop(name, None)
    return result


def _eval_clauses(
    expr: ast.Comprehension,
    clauses,
    i: int,
    frame: Frame,
    thread: Thread,
    result: Any,
) -> None:
    if i == len(clauses):
        if expr.is_dict:
            entry = expr.body
            assert isinstance(entry, ast.DictEntry)
            k = _eval_expr(entry.key, frame, thread)
            check_hashable(k)
            v = _eval_expr(entry.value, frame, thread)
            result[k] = v
        else:
            assert isinstance(expr.body, ast.Expression)
            v = _eval_expr(expr.body, frame, thread)
            result.append(v)
        return
    clause = clauses[i]
    if isinstance(clause, ast.ComprehensionClauseFor):
        iterable = _eval_expr(clause.iterable, frame, thread)
        for item in _iterate(iterable):
            _assign_to_target(clause.vars, item, frame, thread)
            _eval_clauses(expr, clauses, i + 1, frame, thread, result)
    else:
        cond = _eval_expr(clause.cond, frame, thread)
        if truth(cond):
            _eval_clauses(expr, clauses, i + 1, frame, thread, result)


# ---------------------------------------------------------------- iterate / format


def _iterate(value: Any):
    # Per the Starlark spec, strings are NOT iterable. Use s.elems() to
    # iterate over a string's code points. (See docs/spec.md §7.)
    if isinstance(value, str):
        raise EvalError(f"type '{starlark_type(value)}' is not iterable")
    if isinstance(value, (tuple, list, StarlarkList, Dict, StarlarkSet, Range)):
        return iter(value)
    if isinstance(value, dict):
        return iter(value)
    raise EvalError(f"got value of type '{starlark_type(value)}', want 'iterable'")


def _format_float(x: float, conv: str) -> str:
    """Format a float with the given conversion, matching Java/Go's output.

    Differences from Python's format():
    - Inf is rendered "+inf"/"-inf", NaN is "nan".
    - Integer-valued %g/%G results are suffixed with ".0" so `"%g" % 0`
      gives "0.0".
    - %f uses the float's *exact* decimal representation (via Decimal), so
      `"%f" % 1.23e45` produces all digits the IEEE-754 double encodes
      rather than truncating at Python's default 6 fractional digits +
      double precision. Matches Java's BigDecimal-based formatter.
    """
    if x != x:
        return "nan"
    if x == float("inf"):
        return "+inf"
    if x == float("-inf"):
        return "-inf"
    if conv in ("f", "F"):
        from decimal import Decimal

        # Use the shortest round-trip representation (via repr) rather than
        # the exact binary value, so `"%f" % 1.23e45` produces the rounded
        # form Java's BigDecimal-based formatter emits, not the exact
        # bit-pattern decimal.
        d = Decimal(repr(x))
        return f"{d:.6f}"
    if conv in ("g", "G"):
        # str(x) and "%g" % x should give the same answer per the spec.
        from .values import _float_repr

        return _float_repr(x)
    return format(x, conv)


def _str_format(template: str, arg: Any) -> str:
    """Implements `"foo %s" % bar`. Lightweight `%`-style printf.

    Supports %s, %r, %d, %i, %x, %X, %o, %e, %f, %g, %%. Argument may be a
    tuple to fill multiple %-conversions.
    """
    if isinstance(arg, tuple):
        args = list(arg)
    else:
        args = [arg]
    result: list[str] = []
    i = 0
    arg_index = 0
    n = len(template)
    while i < n:
        c = template[i]
        if c != "%":
            result.append(c)
            i += 1
            continue
        i += 1
        if i >= n:
            raise EvalError("incomplete format")
        conv = template[i]
        i += 1
        if conv == "%":
            result.append("%")
            continue
        if arg_index >= len(args):
            raise EvalError("not enough arguments for format string")
        a = args[arg_index]
        arg_index += 1
        if conv == "s":
            from .values import str_starlark

            result.append(str_starlark(a))
        elif conv == "r":
            result.append(repr_starlark(a))
        elif conv in ("d", "i", "x", "X", "o"):
            if isinstance(a, float):
                if a != a:
                    raise EvalError("got nan, want a finite number")
                if a == float("inf"):
                    raise EvalError("got +inf, want a finite number")
                if a == float("-inf"):
                    raise EvalError("got -inf, want a finite number")
                a = int(a)
            elif not _is_int(a):
                raise EvalError(f"got {starlark_type(a)} for '%{conv}' format, want int or float")
            if conv in ("d", "i"):
                # Decimal conversion is capped by CPython's int_max_str_digits;
                # normalize the raw ValueError. Hex/oct (x/X/o below) aren't
                # digit-capped, so format() there needs no guard.
                from .values import _int_to_str

                result.append(_int_to_str(a))
            else:
                result.append(format(a, conv))
        elif conv in ("e", "f", "g", "E", "F", "G"):
            if not _is_num(a):
                raise EvalError(f"got {starlark_type(a)} for '%{conv}' format, want int or float")
            result.append(_format_float(float(a), conv))
        elif conv == "c":
            if _is_int(a):
                # Same range guard as the chr() builtin: a raw chr() leaks a
                # ValueError on out-of-range and an OverflowError on oversized
                # ints (e.g. `'%c' % 1114112`, `'%c' % 10**12`).
                if a < 0 or a > 0x10FFFF:
                    raise EvalError("%c arg not in range(0x110000)")
                result.append(chr(a))
            elif isinstance(a, str) and len(a) == 1:
                result.append(a)
            else:
                raise EvalError("%c requires int or single-char string")
        else:
            raise EvalError(f"unknown format specifier: %{conv}")
    if arg_index < len(args):
        raise EvalError("not all arguments converted during string formatting")
    return "".join(result)


__all__ = ["Frame", "Thread", "call", "eval_file"]
