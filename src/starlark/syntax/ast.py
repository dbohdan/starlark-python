"""Starlark abstract syntax tree.

Mirrors `net.starlark.java.syntax.*` AST node classes. Every node carries the
source-file character offsets it spans (`start`, `end`).

We omit Bazel-specific or experimental nodes: `CastExpression`,
`IsInstanceExpression`, `Ellipsis`, `VarStatement`, type aliases, doc-comment
attachments. The lexer also doesn't emit the corresponding tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .tokens import TokenKind

# --------------------------------------------------------------------- bases


@dataclass(slots=True)
class Node:
    """Base class for every AST node."""

    start: int
    end: int


@dataclass(slots=True)
class Expression(Node):
    pass


@dataclass(slots=True)
class Statement(Node):
    pass


# ------------------------------------------------------------------ literals


@dataclass(slots=True)
class IntLiteral(Expression):
    value: int


@dataclass(slots=True)
class FloatLiteral(Expression):
    value: float


@dataclass(slots=True)
class StringLiteral(Expression):
    value: str


@dataclass(slots=True)
class Identifier(Expression):
    name: str
    # Set by the Resolver. None means "not resolved" (e.g., parser-only run).
    binding: object | None = None


# ------------------------------------------------------------------ operators


@dataclass(slots=True)
class UnaryOperatorExpression(Expression):
    op: TokenKind  # MINUS, PLUS, TILDE, NOT
    operand: Expression


@dataclass(slots=True)
class BinaryOperatorExpression(Expression):
    op: TokenKind
    lhs: Expression
    rhs: Expression


@dataclass(slots=True)
class ConditionalExpression(Expression):
    """`then_expr if cond else else_expr`."""

    then_expr: Expression
    cond: Expression
    else_expr: Expression


# --------------------------------------------------------------- collections


@dataclass(slots=True)
class ListExpression(Expression):
    is_tuple: bool
    elements: list[Expression]


@dataclass(slots=True)
class DictEntry:
    key: Expression
    value: Expression


@dataclass(slots=True)
class DictExpression(Expression):
    entries: list[DictEntry]


# ------------------------------------------------------------- comprehensions


@dataclass(slots=True)
class ComprehensionClauseFor:
    vars: Expression
    iterable: Expression


@dataclass(slots=True)
class ComprehensionClauseIf:
    cond: Expression


ComprehensionClause = ComprehensionClauseFor | ComprehensionClauseIf


@dataclass(slots=True)
class Comprehension(Expression):
    is_dict: bool
    body: object  # Expression for list comp; DictEntry for dict comp.
    clauses: list[ComprehensionClause]
    # Filled by the Resolver:
    locals: list[str] = field(default_factory=list)


# --------------------------------------------------------------- index / call


@dataclass(slots=True)
class IndexExpression(Expression):
    obj: Expression
    index: Expression


@dataclass(slots=True)
class SliceExpression(Expression):
    obj: Expression
    start_index: Expression | None
    end_index: Expression | None
    step: Expression | None


@dataclass(slots=True)
class DotExpression(Expression):
    obj: Expression
    name: Identifier


# --------------------------------------------------------------- arguments


@dataclass(slots=True)
class Argument(Node):
    """One argument in a call expression. See subclasses for the four kinds."""


@dataclass(slots=True)
class PositionalArgument(Argument):
    value: Expression


@dataclass(slots=True)
class KeywordArgument(Argument):
    name: Identifier
    value: Expression


@dataclass(slots=True)
class StarArgument(Argument):
    value: Expression


@dataclass(slots=True)
class StarStarArgument(Argument):
    value: Expression


@dataclass(slots=True)
class CallExpression(Expression):
    fn: Expression
    args: list[Argument]


# ------------------------------------------------------------- parameters


@dataclass(slots=True)
class Parameter(Node):
    """One parameter in a function signature."""


@dataclass(slots=True)
class MandatoryParameter(Parameter):
    name: Identifier


@dataclass(slots=True)
class OptionalParameter(Parameter):
    name: Identifier
    default: Expression


@dataclass(slots=True)
class StarParameter(Parameter):
    """`*` (kw-only marker, name is None) or `*args`."""

    name: Identifier | None


@dataclass(slots=True)
class StarStarParameter(Parameter):
    name: Identifier


# ------------------------------------------------------------- functions


@dataclass(slots=True)
class LambdaExpression(Expression):
    parameters: list[Parameter]
    body: Expression
    # Filled by the Resolver:
    locals: list[str] = field(default_factory=list)
    freevars: list[str] = field(default_factory=list)


# ------------------------------------------------------------- statements


@dataclass(slots=True)
class ExpressionStatement(Statement):
    expression: Expression


@dataclass(slots=True)
class AssignmentStatement(Statement):
    """`lhs = rhs` or `lhs op= rhs` (op is None for plain `=`)."""

    lhs: Expression
    op: TokenKind | None  # PLUS, MINUS, ... or None for plain assignment
    rhs: Expression


@dataclass(slots=True)
class IfStatement(Statement):
    """Represents `if cond: body [else: else_block]`.

    `elif` chains are represented as nested IfStatements in `else_block`.
    """

    cond: Expression
    body: list[Statement]
    else_block: list[Statement] = field(default_factory=list)


@dataclass(slots=True)
class ForStatement(Statement):
    vars: Expression
    iterable: Expression
    body: list[Statement]


@dataclass(slots=True)
class DefStatement(Statement):
    name: Identifier
    parameters: list[Parameter]
    body: list[Statement]
    # Filled by the Resolver:
    locals: list[str] = field(default_factory=list)
    freevars: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ReturnStatement(Statement):
    value: Expression | None


@dataclass(slots=True)
class FlowStatement(Statement):
    """`break`, `continue`, or `pass`."""

    kind: TokenKind  # BREAK, CONTINUE, PASS


# --------------------------------------------------------------- load


@dataclass(slots=True)
class LoadBinding:
    local: Identifier
    original: Identifier  # may equal `local` for `load(..., "x")`


@dataclass(slots=True)
class LoadStatement(Statement):
    module: StringLiteral
    bindings: list[LoadBinding]


# --------------------------------------------------------------- file


@dataclass(slots=True)
class StarlarkFile:
    """The result of parsing a `.star` file."""

    file: str
    statements: list[Statement]
    errors: list  # list[SyntaxError]; avoid circular import in annotations
    # Filled by the Resolver:
    globals: list[str] = field(default_factory=list)


__all__ = [
    "Argument",
    "AssignmentStatement",
    "BinaryOperatorExpression",
    "CallExpression",
    "Comprehension",
    "ComprehensionClause",
    "ComprehensionClauseFor",
    "ComprehensionClauseIf",
    "ConditionalExpression",
    "DefStatement",
    "DictEntry",
    "DictExpression",
    "DotExpression",
    "Expression",
    "ExpressionStatement",
    "FloatLiteral",
    "FlowStatement",
    "ForStatement",
    "Identifier",
    "IfStatement",
    "IndexExpression",
    "IntLiteral",
    "KeywordArgument",
    "LambdaExpression",
    "ListExpression",
    "LoadBinding",
    "LoadStatement",
    "MandatoryParameter",
    "Node",
    "OptionalParameter",
    "Parameter",
    "PositionalArgument",
    "ReturnStatement",
    "SliceExpression",
    "StarArgument",
    "StarParameter",
    "StarStarArgument",
    "StarStarParameter",
    "StarlarkFile",
    "Statement",
    "StringLiteral",
    "UnaryOperatorExpression",
]
