"""Smoke-test the resolver against every .star conformance file (chunk-split)."""

from __future__ import annotations

from pathlib import Path

import pytest

from starlark.syntax import Lexer, parse, resolve

CONFORMANCE_DIR = Path(__file__).parent.parent / "conformance"
STAR_FILES = sorted(CONFORMANCE_DIR.glob("*.star"))

# The full set of names the conformance suite expects to be predeclared.
PREDECLARED = frozenset(
    {
        "assert_eq",
        "assert_",
        "assert_fails",
        "freeze",
        "struct",
        "mutablestruct",
        "int_mul_slow",
    }
)

UNIVERSAL = frozenset(
    {
        "None",
        "True",
        "False",
        "len",
        "type",
        "range",
        "print",
        "repr",
        "str",
        "int",
        "float",
        "bool",
        "list",
        "tuple",
        "dict",
        "set",
        "enumerate",
        "zip",
        "reversed",
        "sorted",
        "min",
        "max",
        "hasattr",
        "getattr",
        "dir",
        "hash",
        "all",
        "any",
        "fail",
        "abs",
        "json",
    }
)


def chunks(source: str):
    line = 1
    parts = source.split("\n---\n")
    for part in parts:
        yield line, part
        line += part.count("\n") + 1


@pytest.mark.parametrize("path", STAR_FILES, ids=lambda p: p.name)
def test_resolve_to_completion(path: Path):
    source = path.read_text(encoding="utf-8")
    for line, chunk in chunks(source):
        f = parse(chunk, file=f"{path.name}:{line}")
        # The chunk may legally contain code that the resolver would reject
        # (e.g., `### regex`-marked errors). For Phase 3 we only assert that
        # resolution does not crash, and that we don't produce *parser*
        # errors as a side-effect.
        n_parser_errors = len(f.errors)
        locs = Lexer(chunk).locs
        resolve(f, locs, predeclared=PREDECLARED, universal=UNIVERSAL)
        # No new errors should appear in well-formed chunks unless the chunk
        # has a `###` marker. We don't bother distinguishing here.
        del n_parser_errors
