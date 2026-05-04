"""Smoke-test the parser against every .star conformance file."""

from __future__ import annotations

from pathlib import Path

import pytest

from starlark.syntax import parse

CONFORMANCE_DIR = Path(__file__).parent.parent / "conformance"
STAR_FILES = sorted(CONFORMANCE_DIR.glob("*.star"))


def chunks(source: str):
    """Yield (line_num, text) for each `---`-separated chunk, like ScriptTest.java."""
    line = 1
    parts = source.split("\n---\n")
    for part in parts:
        yield line, part
        line += part.count("\n") + 1  # the `---\n` itself counts as one line


@pytest.mark.parametrize("path", STAR_FILES, ids=lambda p: p.name)
def test_parse_to_completion(path: Path):
    source = path.read_text(encoding="utf-8")
    for line, chunk in chunks(source):
        # The Java driver also strips chunk-internal "### regex" error
        # expectations only at the *evaluation* layer; at parse time those are
        # just comments and we leave them alone.
        f = parse(chunk, file=f"{path.name}:{line}")
        assert not f.errors, [str(e) for e in f.errors[:5]]
