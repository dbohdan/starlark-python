"""Cross-validation against the starlark-go reference implementation.

If `starlark` (from go.starlark.net/cmd/starlark) is on PATH we run a
hand-curated set of small programs through both implementations and
assert that exit status *and* stdout match byte-for-byte.

We don't replay the Bazel conformance suite verbatim because that suite
calls `assert_eq`/etc. which are predeclared by Bazel's ScriptTest
driver and not by the standalone go CLI. Reproducing Bazel's driver
inside the go CLI is more trouble than the test is worth — these short
programs cover the same ground.

Skipped cleanly when the go binary is absent.
"""

from __future__ import annotations

import contextlib
import io
import shutil
import subprocess

import pytest

import starlark

# We install our own CLI as `starlark-python` precisely so this lookup
# unambiguously finds the go reference (or nothing).
STAR_BIN = shutil.which("starlark")


pytestmark = pytest.mark.skipif(
    STAR_BIN is None,
    reason="starlark-go CLI not installed — install go.starlark.net/cmd/starlark to enable",
)


def _run_go(source: str) -> tuple[int, str]:
    """Run `source` under starlark-go. `print()` writes to stderr there.

    `-globalreassign` lifts the BUILD-mode restriction that forbids top-level
    `if` and `for`, matching our interpreter's permissive default.
    """
    assert STAR_BIN is not None  # pytestmark skip guarantees this
    p = subprocess.run(
        [STAR_BIN, "-globalreassign", "-c", source],
        capture_output=True,
        timeout=10,
        text=True,
        check=False,
    )
    # Concatenate stderr (where print goes) and stdout (where REPL repr would go).
    return p.returncode, p.stderr + p.stdout


def _run_python(source: str) -> tuple[int, str]:
    """Run `source` under our interpreter. `print()` writes to stderr too."""
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            starlark.exec_file(source, filename="<cross>")
    except Exception:
        return 1, err.getvalue()
    return 0, err.getvalue()


# Each program is a small valid Starlark snippet that prints something.
# Both implementations should produce identical stdout. The names are
# chosen so pytest -v output reads like a feature checklist.
PROGRAMS: dict[str, str] = {
    "arithmetic": "print(1 + 2 * 3 - 4)",
    "integer_division": "print(7 // 2, 7 % 2)",
    "float_arith": "print(1.5 + 2.5)",
    "comparisons": "print(1 < 2, 2 <= 2, 3 > 2, 'a' < 'b')",
    "string_methods": 'print("hello".upper(), "abc,def".split(","))',
    "list_ops": "print([1, 2, 3] + [4, 5])",
    "dict_ops": 'print({"a": 1, "b": 2})',
    "tuple_ops": "print((1, 2, 3))",
    "for_loop": (
        "total = 0\n"
        "for i in range(5):\n"
        "    total += i\n"
        "print(total)\n"
    ),
    "if_else": (
        "x = 5\n"
        "if x > 0:\n"
        "    print('pos')\n"
        "elif x < 0:\n"
        "    print('neg')\n"
        "else:\n"
        "    print('zero')\n"
    ),
    "list_comprehension": "print([x*2 for x in range(5) if x % 2 == 0])",
    "dict_comprehension": "print({k: k*k for k in range(4)})",
    "function_def": (
        "def add(a, b):\n"
        "    return a + b\n"
        "print(add(2, 3))\n"
    ),
    "lambda": "print((lambda x: x * x)(7))",
    "closure": (
        "def outer(n):\n"
        "    def inner():\n"
        "        return n\n"
        "    return inner()\n"
        "print(outer(42))\n"
    ),
    "tuple_unpacking": "a, b = 1, 2\nprint(a, b)\n",
    "string_format": 'print("%d %s" % (3, "hi"))',
    "json_round_trip": (
        'x = {"a": [1, 2], "b": "hi"}\n'
        "encoded = json.encode(x)\n"
        "print(encoded)\n"
        "y = json.decode(encoded)\n"
        'print(y["a"], y["b"])\n'
    ),
    "sorted_with_key": "print(sorted([3, 1, 2], reverse=True))",
    "min_max": "print(min(5, 1, 3), max(5, 1, 3))",
    "len_and_type": 'print(len("hello"), type([]))',
    "bool_truth": 'print(bool(0), bool(1), bool(""), bool("x"))',
    "membership": "print(2 in [1, 2, 3], 'k' in {'k': 1})",
}


@pytest.mark.parametrize("name", list(PROGRAMS), ids=list(PROGRAMS))
def test_cross(name: str) -> None:
    source = PROGRAMS[name]
    go_status, go_out = _run_go(source)
    py_status, py_out = _run_python(source)
    assert go_status == py_status, (
        f"exit status differs: go={go_status} python={py_status}\n"
        f"go stdout: {go_out!r}\npython stdout: {py_out!r}"
    )
    assert go_out == py_out, (
        f"stdout differs:\n  go:     {go_out!r}\n  python: {py_out!r}"
    )
