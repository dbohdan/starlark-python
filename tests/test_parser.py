"""Tests for the parser."""

from __future__ import annotations

from starlark.syntax import ast, parse, parse_expression
from starlark.syntax.tokens import TokenKind


def parse_or_raise(source: str):
    f = parse(source)
    assert not f.errors, [str(e) for e in f.errors]
    return f.statements


def test_empty_file():
    f = parse("")
    assert f.statements == []
    assert not f.errors


def test_simple_assignment():
    [stmt] = parse_or_raise("x = 1\n")
    assert isinstance(stmt, ast.AssignmentStatement)
    assert stmt.op is None
    assert isinstance(stmt.lhs, ast.Identifier)
    assert stmt.lhs.name == "x"
    assert isinstance(stmt.rhs, ast.IntLiteral)
    assert stmt.rhs.value == 1


def test_aug_assignment():
    [stmt] = parse_or_raise("x += 2\n")
    assert isinstance(stmt, ast.AssignmentStatement)
    assert stmt.op == TokenKind.PLUS


def test_arithmetic_precedence():
    e = parse_expression("1 + 2 * 3")
    assert isinstance(e, ast.BinaryOperatorExpression)
    assert e.op == TokenKind.PLUS
    assert isinstance(e.rhs, ast.BinaryOperatorExpression)
    assert e.rhs.op == TokenKind.STAR


def test_comparison_not_associative():
    f = parse("x = 1 < 2 < 3\n")
    assert any("not associative" in e.message for e in f.errors)


def test_unary_minus():
    e = parse_expression("-x")
    assert isinstance(e, ast.UnaryOperatorExpression)
    assert e.op == TokenKind.MINUS


def test_not_in_synthesis():
    e = parse_expression("x not in y")
    assert isinstance(e, ast.BinaryOperatorExpression)
    assert e.op == TokenKind.NOT_IN


def test_call_expression():
    e = parse_expression("f(1, x, *a, **b, k=2)")
    assert isinstance(e, ast.CallExpression)
    kinds = [type(a).__name__ for a in e.args]
    assert kinds == [
        "PositionalArgument",
        "PositionalArgument",
        "StarArgument",
        "StarStarArgument",
        "KeywordArgument",
    ]


def test_member_and_index():
    e = parse_expression("a.b[0]")
    assert isinstance(e, ast.IndexExpression)
    assert isinstance(e.obj, ast.DotExpression)
    assert e.obj.name.name == "b"


def test_slice_full():
    e = parse_expression("a[1:2:3]")
    assert isinstance(e, ast.SliceExpression)
    assert isinstance(e.start_index, ast.IntLiteral) and e.start_index.value == 1
    assert isinstance(e.end_index, ast.IntLiteral) and e.end_index.value == 2
    assert isinstance(e.step, ast.IntLiteral) and e.step.value == 3


def test_slice_partial():
    e = parse_expression("a[:5]")
    assert isinstance(e, ast.SliceExpression)
    assert e.start_index is None
    assert isinstance(e.end_index, ast.IntLiteral) and e.end_index.value == 5
    assert e.step is None


def test_list_literal():
    e = parse_expression("[1, 2, 3]")
    assert isinstance(e, ast.ListExpression)
    assert not e.is_tuple
    assert len(e.elements) == 3


def test_tuple_literal():
    e = parse_expression("(1, 2)")
    assert isinstance(e, ast.ListExpression)
    assert e.is_tuple


def test_dict_literal():
    e = parse_expression("{'a': 1, 'b': 2}")
    assert isinstance(e, ast.DictExpression)
    assert len(e.entries) == 2


def test_list_comprehension():
    e = parse_expression("[x*2 for x in xs if x > 0]")
    assert isinstance(e, ast.Comprehension)
    assert not e.is_dict
    assert len(e.clauses) == 2


def test_dict_comprehension():
    e = parse_expression("{k: v for k, v in items}")
    assert isinstance(e, ast.Comprehension)
    assert e.is_dict


def test_string_concat_folded():
    e = parse_expression("'a' + 'b'")
    assert isinstance(e, ast.StringLiteral)
    assert e.value == "ab"


def test_implicit_concat_forbidden():
    f = parse('x = "a" "b"\n')
    assert any("implicit string concatenation" in e.message for e in f.errors)


def test_def_statement():
    [stmt] = parse_or_raise("def f(x, y=2, *args, **kw):\n    return x + y\n")
    assert isinstance(stmt, ast.DefStatement)
    assert stmt.name.name == "f"
    kinds = [type(p).__name__ for p in stmt.parameters]
    assert kinds == [
        "MandatoryParameter",
        "OptionalParameter",
        "StarParameter",
        "StarStarParameter",
    ]
    assert len(stmt.body) == 1
    assert isinstance(stmt.body[0], ast.ReturnStatement)


def test_lambda():
    e = parse_expression("lambda x, y=1: x + y")
    assert isinstance(e, ast.LambdaExpression)
    assert len(e.parameters) == 2


def test_if_elif_else():
    [stmt] = parse_or_raise(
        "if x:\n"
        "    a()\n"
        "elif y:\n"
        "    b()\n"
        "else:\n"
        "    c()\n"
    )
    assert isinstance(stmt, ast.IfStatement)
    assert len(stmt.body) == 1
    assert len(stmt.else_block) == 1
    assert isinstance(stmt.else_block[0], ast.IfStatement)
    assert len(stmt.else_block[0].else_block) == 1


def test_for_statement():
    [stmt] = parse_or_raise("for i in xs:\n    print(i)\n")
    assert isinstance(stmt, ast.ForStatement)
    assert isinstance(stmt.vars, ast.Identifier)


def test_for_tuple_vars():
    [stmt] = parse_or_raise("for k, v in items:\n    pass\n")
    assert isinstance(stmt, ast.ForStatement)
    assert isinstance(stmt.vars, ast.ListExpression)
    assert stmt.vars.is_tuple


def test_load_statement():
    [stmt] = parse_or_raise('load("m.bzl", "x", y = "z")\n')
    assert isinstance(stmt, ast.LoadStatement)
    assert stmt.module.value == "m.bzl"
    assert len(stmt.bindings) == 2
    assert stmt.bindings[0].local.name == "x"
    assert stmt.bindings[0].original.name == "x"
    assert stmt.bindings[1].local.name == "y"
    assert stmt.bindings[1].original.name == "z"


def test_conditional_expression():
    e = parse_expression("a if cond else b")
    assert isinstance(e, ast.ConditionalExpression)


def test_break_continue_pass():
    [for_stmt] = parse_or_raise(
        "for i in xs:\n"
        "    if i:\n"
        "        break\n"
        "    elif i == 0:\n"
        "        continue\n"
        "    else:\n"
        "        pass\n"
    )
    assert isinstance(for_stmt, ast.ForStatement)
    body = for_stmt.body[0]  # the if
    flow_kinds = []
    cur = body
    while isinstance(cur, ast.IfStatement):
        if cur.body and isinstance(cur.body[0], ast.FlowStatement):
            flow_kinds.append(cur.body[0].kind)
        if cur.else_block and isinstance(cur.else_block[0], ast.IfStatement):
            cur = cur.else_block[0]
        else:
            if cur.else_block and isinstance(cur.else_block[0], ast.FlowStatement):
                flow_kinds.append(cur.else_block[0].kind)
            break
    assert TokenKind.BREAK in flow_kinds
    assert TokenKind.CONTINUE in flow_kinds
    assert TokenKind.PASS in flow_kinds


def test_forbidden_keyword_while():
    f = parse("while True:\n    pass\n")
    assert any("'while' not supported" in e.message for e in f.errors)


def test_forbidden_keyword_import():
    f = parse("import x\n")
    assert any("'import' not supported" in e.message for e in f.errors)


def test_multiline_in_brackets():
    [stmt] = parse_or_raise("x = [\n    1,\n    2,\n    3,\n]\n")
    assert isinstance(stmt, ast.AssignmentStatement)
    assert isinstance(stmt.rhs, ast.ListExpression)
    assert len(stmt.rhs.elements) == 3


def test_unparenthesized_tuple_assignment():
    [stmt] = parse_or_raise("a, b = 1, 2\n")
    assert isinstance(stmt, ast.AssignmentStatement)
    assert isinstance(stmt.lhs, ast.ListExpression)
    assert stmt.lhs.is_tuple
    assert isinstance(stmt.rhs, ast.ListExpression)
    assert stmt.rhs.is_tuple


def test_empty_tuple():
    e = parse_expression("()")
    assert isinstance(e, ast.ListExpression)
    assert e.is_tuple
    assert e.elements == []


def test_nested_function():
    [stmt] = parse_or_raise(
        "def outer():\n"
        "    def inner():\n"
        "        return 1\n"
        "    return inner\n"
    )
    assert isinstance(stmt, ast.DefStatement)
    assert isinstance(stmt.body[0], ast.DefStatement)
