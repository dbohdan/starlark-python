"""Command-line interface for the Starlark interpreter.

We deliberately install as `starlark-python` (not `starlark`) so the
script doesn't shadow go.starlark.net's `starlark` binary, which we want
to use for cross-validation tests.

Usage:

    starlark-python [SCRIPT.star]                  # run a file
    starlark-python -c "1 + 1"                     # evaluate an expression
    starlark-python                                # interactive REPL

The same entry point is reachable as `python starlark-python.pyz` when
built via `poe zipapp`.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path
from typing import Any

from . import EvalError, exec_file
from . import compile as compile_starlark
from .eval.loader import FileLoader
from .syntax.errors import StarlarkSyntaxException

with contextlib.suppress(ModuleNotFoundError):
    import readline  # noqa: F401


def evaluate(source: str, globals: dict[Any, Any]) -> tuple[Any, dict[Any, Any]]:
    program = compile_starlark(source)

    if program.is_expression:
        return (program.eval(**globals), globals)

    m = program.exec(predeclared=globals)
    return (None, globals | m.globals)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starlark-python")

    parser.add_argument(
        "-c",
        dest="source",
        metavar="SOURCE",
        help="evaluate the given source and print the result",
    )
    parser.add_argument(
        "script",
        nargs="?",
        type=Path,
        help="path to a .star file to run",
    )

    args = parser.parse_args(argv)

    if args.source is not None:
        try:
            value, _ = evaluate(args.source, {})
        except (EvalError, StarlarkSyntaxException) as e:
            print(f"starlark: {e}", file=sys.stderr)
            return 1

        if value is not None:
            from .eval.values import repr_starlark

            print(repr_starlark(value))

        return 0

    if args.script is not None:
        try:
            source = args.script.read_text(encoding="utf-8")
        except OSError as e:
            print(f"starlark: {e}", file=sys.stderr)

            return 1

        loader = FileLoader(
            exec_file=exec_file,
            search_paths=[str(args.script.parent), "."],
        )

        try:
            exec_file(source, filename=str(args.script), loader=loader)
        except (EvalError, StarlarkSyntaxException) as e:
            print(f"starlark: {e}", file=sys.stderr)

            return 1

        return 0

    # No args: minimal REPL.
    return _repl()


def _repl() -> int:
    globals = {}

    print("Starlark (starlark-python). Press Ctrl+D to exit.")

    while True:
        try:
            line = input(">>> ")
        except (EOFError, KeyboardInterrupt):
            print()

            return 0

        if not line.strip():
            continue

        try:
            value, globals = evaluate(line, globals)
        except (EvalError, StarlarkSyntaxException) as e:
            print(f"starlark: {e}", file=sys.stderr)

            continue

        if value is not None:
            from .eval.values import repr_starlark

            print(repr_starlark(value))


if __name__ == "__main__":
    sys.exit(main())
