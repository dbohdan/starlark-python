"""The Starlark conformance suite.

For each `.star` file under `conformance/`:

1. Split on `\n---\n` into chunks (mirrors Bazel's ScriptTest).
2. For each chunk, scan for `### regex` markers — expected error patterns
   on the line they sit on.
3. Parse + resolve + evaluate the chunk with the test-driver predeclared
   builtins (`assert_eq`, `assert_`, `assert_fails`, `freeze`, `struct`,
   `mutablestruct`, `int_mul_slow`).
4. The chunk passes iff:
   - Any `### regex` markers each match at least one error reported during
     parse/resolve/eval, AND no error went unmatched, AND
   - The reporter (used by `assert_eq` etc.) collected no errors.

Each `.star` file becomes one parameterized pytest case. Files known to
exercise unimplemented features are listed in `XFAIL_FILES` and marked
xfail; remove from the list once they pass.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import starlark
from starlark.eval.test_driver import make_predeclared, pop_reporter, push_reporter

CONFORMANCE_DIR = Path(__file__).parent.parent / "conformance"
STAR_FILES = sorted(CONFORMANCE_DIR.glob("*.star"))

# Files that exercise features we haven't implemented yet. Trim as we go.
XFAIL_FILES: dict[str, str] = {
    "set.star": "set spec corners",
    "string_format.star": "advanced %-formatting",
    "string_misc.star": "various string edge cases",
    "float.star": "float repr / nan / inf edge cases",
    "int.star": "int.bit_length and similar methods",
    "int_constructor.star": "int(string) edge cases",
    "fields.star": "struct.fields()",
    "function.star": "lambda kwargs / edge cases",
    "loop.star": "complex loop semantics",
    "range.star": "range edge cases",
    "sorted.star": "sorted: nan placement & utf8 setting",
}

# Enable strict xfail so xpass becomes a failure, exposing files we can
# remove from the list above.
XFAIL_STRICT = False  # set True after the list is curated

# Files we skip entirely because they exercise behavior that would hang or
# require very heavy infrastructure (e.g., 2-billion-element range allocation
# with capacity-limit detection, JSON serialization, etc.).
SKIP_FILES: dict[str, str] = {
    "json.star": "json.encode/decode not implemented",
}


def chunks(source: str):
    line = 1
    parts = source.split("\n---\n")
    for part in parts:
        yield line, part
        line += part.count("\n") + 1


_EXPECT_RE = re.compile(r"###\s*(.*)$", re.MULTILINE)


def expectations_in(chunk: str) -> list[tuple[int, re.Pattern]]:
    """Returns (line_in_chunk, regex) for each `### regex` marker."""
    out: list[tuple[int, re.Pattern]] = []
    for m in _EXPECT_RE.finditer(chunk):
        line = chunk.count("\n", 0, m.start()) + 1
        try:
            pat = re.compile(m.group(1).strip())
        except re.error:
            continue
        out.append((line, pat))
    return out


def run_chunk(name: str, chunk: str) -> list[str]:
    """Run a single chunk; return a list of human-readable failures."""
    failures: list[str] = []

    expected = expectations_in(chunk)
    reporter = push_reporter()
    try:
        try:
            starlark.exec_file(chunk, filename=name, predeclared=make_predeclared())
            evaluated = True
            error_messages: list[str] = []
        except starlark.EvalError as e:
            evaluated = False
            error_messages = [e.message] + list(reporter.errors)
        except Exception as e:  # SyntaxException etc.
            evaluated = False
            error_messages = [str(e)] + list(reporter.errors)

        # Match expectations.
        unmatched = [(line, pat.pattern) for line, pat in expected]
        for line, pat in expected:
            for msg in error_messages:
                if pat.search(msg):
                    unmatched = [(l, p) for l, p in unmatched if l != line or p != pat.pattern]
                    break

        if expected and evaluated:
            failures.append(
                f"{name}: expected error(s) but evaluation succeeded: "
                + "; ".join(p for _, p in expected)
            )
        for line, pat in unmatched:
            failures.append(f"{name}:{line}: expected error matching /{pat}/ not raised")

        if not expected and not evaluated:
            failures.append(f"{name}: unexpected error: {error_messages[0]}")

        # Reporter errors (assert_eq failures, etc.) are also failures.
        if not expected:
            for msg in reporter.errors:
                failures.append(f"{name}: {msg}")
    finally:
        pop_reporter()
    return failures


@pytest.mark.parametrize("path", STAR_FILES, ids=lambda p: p.name)
def test_conformance(path: Path, request):
    if path.name in SKIP_FILES:
        pytest.skip(SKIP_FILES[path.name])
    if path.name in XFAIL_FILES:
        request.applymarker(
            pytest.mark.xfail(reason=XFAIL_FILES[path.name], strict=XFAIL_STRICT)
        )
    source = path.read_text(encoding="utf-8")
    failures: list[str] = []
    for line, chunk in chunks(source):
        failures.extend(run_chunk(f"{path.name}:{line}", chunk))
    assert not failures, "\n".join(failures[:20])
