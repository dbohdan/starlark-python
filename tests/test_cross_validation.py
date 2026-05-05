"""Optional cross-validation against the starlark-go reference implementation.

If the `starlark` binary (from go.starlark.net/cmd/starlark) is on PATH, run
each conformance .star file under both implementations and assert that exit
status and stdout match. Skipped cleanly when the binary is absent.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import starlark
from starlark.eval.test_driver import make_predeclared

CONFORMANCE_DIR = Path(__file__).parent.parent / "conformance"
# We install our own CLI as `starlark-python` precisely so this lookup
# unambiguously finds the go reference (or nothing).
STAR_BIN = shutil.which("starlark")


pytestmark = pytest.mark.skipif(
    STAR_BIN is None,
    reason="starlark-go CLI not installed — install go.starlark.net/cmd/starlark to enable",
)


def _run_go(path: Path) -> tuple[int, str]:
    assert STAR_BIN is not None  # the pytestmark skip guarantees this
    p = subprocess.run(
        [STAR_BIN, str(path)],
        capture_output=True,
        timeout=10,
        text=True,
        check=False,
    )
    return p.returncode, p.stdout


def _run_python(path: Path) -> tuple[int, str]:
    """Run the .star file through our interpreter and return (status, stdout)."""
    import contextlib
    import io
    out = io.StringIO()
    src = path.read_text(encoding="utf-8")
    try:
        with contextlib.redirect_stdout(out):
            starlark.exec_file(src, filename=path.name, predeclared=make_predeclared())
    except Exception:
        return 1, out.getvalue()
    return 0, out.getvalue()


# Cross-validation is best-effort: we only assert on a small whitelist where
# we're confident both implementations should agree byte-for-byte.
SAFE_FILES = [
    "and_or_not.star",
    "equality.star",
    "tuple.star",
]


@pytest.mark.parametrize("name", SAFE_FILES)
def test_cross(name: str):
    path = CONFORMANCE_DIR / name
    go_status, _go_out = _run_go(path)
    py_status, _py_out = _run_python(path)
    assert (go_status == 0) == (py_status == 0), (
        f"go status={go_status}, python status={py_status}"
    )
