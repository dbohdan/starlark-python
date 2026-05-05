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

# Files left as xfail after the spec-compliance push. Each remaining failure
# is a documented divergence from the Java reference rather than a bug:
# - json.star, sorted.star: depend on UTF-16 string indexing for surrogate
#   handling and string ordering.
# - range.star: depends on Java's signed-32-bit `range()` argument check;
#   we use arbitrary-precision int.
# - fields.star: depends on Bazel's `mutablestruct` test helper rejecting
#   type-changing field reassignment, which is not part of the language.
# All four are documented under "Compatibility" in docs/README.md.
XFAIL_FILES: dict[str, str] = {
    "json.star": "Java UTF-16 indexing for surrogate halves",
    "fields.star": "mutablestruct type-tracking is a Bazel test helper",
    "range.star": "Java signed-32-bit range() argument check",
    "sorted.star": "non-BMP string ordering depends on UTF-16",
}

XFAIL_STRICT = True  # ensure removed-and-passing files are flagged

# Files we skip entirely because they exercise behavior that would hang or
# require very heavy infrastructure (e.g., 2-billion-element range allocation
# with capacity-limit detection, JSON serialization, etc.).
SKIP_FILES: dict[str, str] = {}


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
    # The conformance suite occasionally probes Bazel-specific feature flags
    # by name (e.g. `_utf8_byte_strings`). We expose them as predeclared
    # globals set to False so the gated branches pick the non-Bazel path.
    pre = make_predeclared()
    pre["_utf8_byte_strings"] = False
    try:
        try:
            starlark.exec_file(chunk, filename=name, predeclared=pre)
            evaluated = True
            error_messages: list[str] = []
        except starlark.EvalError as e:
            evaluated = False
            error_messages = [e.message, *reporter.errors]
        except Exception as e:  # SyntaxException etc.
            evaluated = False
            error_messages = [str(e), *reporter.errors]

        # Match expectations.
        unmatched = [(line, pat.pattern) for line, pat in expected]
        for line, pat in expected:
            for msg in error_messages:
                if pat.search(msg):
                    unmatched = [
                        (ml, mp) for ml, mp in unmatched if ml != line or mp != pat.pattern
                    ]
                    break

        if expected and evaluated:
            failures.append(
                f"{name}: expected error(s) but evaluation succeeded: "
                + "; ".join(p.pattern for _, p in expected)
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
        request.applymarker(pytest.mark.xfail(reason=XFAIL_FILES[path.name], strict=XFAIL_STRICT))
    source = path.read_text(encoding="utf-8")
    failures: list[str] = []
    for line, chunk in chunks(source):
        failures.extend(run_chunk(f"{path.name}:{line}", chunk))
    assert not failures, "\n".join(failures[:20])
