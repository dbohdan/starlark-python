# Starlark in Python

[![PyPI package version badge.](https://img.shields.io/pypi/v/starlark)](https://pypi.org/project/starlark/)
![Python 3.11, 3.12, 3.13, 3.14 supported.](https://img.shields.io/badge/python-3.11_%7C_3.12_%7C_3.13_%7C_3.14-blue)
[![PyPI download statistics badge.](https://img.shields.io/pypi/dm/starlark)](https://pypistats.org/packages/starlark)

This project provides a pure-Python implementation of the [Starlark][starlark] configuration language.
Starlark in Python was ported by AI from the Java reference implementation that ships with [Bazel][bazel].
You can read [how it was ported](https://dbohdan.com/starlark-python).

[starlark]: https://github.com/bazelbuild/starlark
[bazel]: https://github.com/bazelbuild/bazel

## Status

Conformance test files are passing with the exception of 4 [expected failures](https://docs.pytest.org/en/stable/how-to/skipping.html).
Those are all documented divergences from the Java reference (UTF-16 string indexing, 32-bit `range()` bounds, and a Bazel-specific `mutablestruct` test helper).

## Goals

- Pure Python
  - Therefore usable in a cross-platform [zipapp](https://docs.python.org/3/library/zipapp.html)
- No dependencies
- Simple implementation (a tree-walking interpreter)
- [Safe to run untrusted code](#security)
- Passes the conformance suite from Bazel (copied verbatim in [`conformance/`](conformance/))

## Non-goals

- Performance
- Supporting old Python versions (3.11+ is currently required)

## Quick start

```python
import starlark

# Evaluate an expression.
starlark.eval("1 + 2 * 3")  # 7

# Run a Starlark file.
m = starlark.exec_file('''
def fact(n):
    result = 1
    for i in range(1, n + 1):
        result *= i
    return result

z = fact(5)
''')

m.globals["z"]  # 120
```
## Users

- [dbohdan.com SSG](https://dbohdan.com/about#metadata-reuse): the site owner has switched the custom static site generator from TOML to Starlark for metadata reuse.
- [Lark Cycles](https://github.com/dbohdan/lark-cycles): this Python/Tkinter/Starlark port of the 1988 Amiga programming game [_Warrior Cycles_](https://corewar.co.uk/warriorcycles.htm) by Rico Mariana was developed as a demo for Starlark in Python.
- [Remarshal](https://github.com/remarshal-project/remarshal): a format converter between CBOR, JSON, MessagePack, TOML, and YAML 1.1 & 1.2.
  Remarshal gained the ability to modify the data it converted with Starlark.
  Part of the motivation for Starlark in Python was to add this functionality without a Go or Rust dependency.

## API

See [`docs/`](docs/).

## CLI

The package installs a `starlark-python` console script.
(We picked a suffixed name so it doesn't shadow `starlark` from go.starlark.net, which we use for cross-validation.)
It can also be run as a zipapp:

```sh
poe zipapp                                 # builds ./starlark-python.pyz (~560K)
./starlark-python.pyz -c "1 + 2 * 3"       # 7
./starlark-python.pyz path/to/script.star
```

## `load()` and the host API

The runtime does not load files itself; the host supplies a `Loader` callable.
`eval/loader.py` ships a simple file-based loader you can plug in:

```python
from starlark.eval.loader import FileLoader
import starlark

loader = FileLoader(exec_file=starlark.exec_file, search_paths=[".", "lib"])
starlark.exec_file(open("main.star").read(), loader=loader)
```

`load("foo.star", "bar")` then resolves `foo.star` against `loader`.
`FileLoader` only allows loading files from the directories in `search_paths`;
it rejects absolute paths, `..` traversal, and symlink escapes.
List just those directories that you want Starlark code to access.

## Security

Starlark in Python is new and has **not** been extensively reviewed and tested.

Starlark is a sandboxed language.
A `.star` program cannot read or write files, open sockets, spawn processes, or reach any Python object the host did not explicitly hand it.
Opt-on resource limits (`max_steps`, `max_allocs`) limit CPU and memory for hosts that accept untrusted input.

What we defend against, what we don't defend against, and the
public limits API are documented in [`security/threat-model.md`](security/threat-model.md).
In short: we mitigate DoS-style malicious values; defending against deliberately crafted (but otherwise valid) values is a host responsibility, the same as with JSON or TOML.

## Documented divergences from the Java reference

These are intentional:

- **Integers are Python `int`.**
  Arbitrary precision; no overflow.
  The Java reference uses a `StarlarkInt` type that is a union of `int32`, `int64`, and `BigInteger`.
- **Integer magnitude is bounded.**
  A Starlark integer is hard-capped at `MAX_INT_BITS = 2^19` bits (~158k decimal digits) to bound per-operation CPU.
  The Java reference's `BigInteger` is unbounded; this cap is far above any realistic configuration value, and operations that would exceed it raise a clean `EvalError`.
- **Strings are indexed by Unicode code point.**
  The Java reference indexes by UTF-16 code unit, which produces surprising results for non-BMP characters.
  The spec leaves this implementation-defined.
- **No 32-bit range checks for `range()`, `*` repeat, etc.**
  The Java reference rejects allocations whose length doesn't fit in a signed 32-bit int.
  We instead cap container allocations at 16M elements with a less specific error message.

The conformance suite includes a handful of tests that depend on the Java reference's exact error wording for these checks;
they are listed in `XFAIL_FILES` in `tests/test_conformance.py`.

## Layout

- [**`conformance/`**](conformance/) – `.star` conformance tests, copied from Bazel.
- [**`src/starlark/`**](src/starlark/) – The actual port.
  - [`eval/`](src/starlark/eval/) – Value model, evaluator, builtins, methods, loader.
  - [`syntax/`](src/starlark/syntax/) – Lexer, parser, AST, resolver.
  - [`cmd.py`](src/starlark/cmd.py) – CLI entry point.
- [`tests/`](tests/) – Pytest suite (unit + conformance + property-based).
- [`HISTORY.md`](HISTORY.md) – Original 14-phase plan + append-only journal.

## Development

Install [Poe the Poet](https://poethepoet.natn.io/) to run the tasks (`uv tool install poethepoet`, `pipx install poethepoet`).

```sh
uv sync           # Install deps
poe test          # ~610 tests, ~3s
poe lint          # Ruff
poe typecheck     # Pyright
poe zipapp        # Build ./starlark-python.pyz
```

`tests/test_cross_validation.py` runs a curated set of programs under both this interpreter and the [starlark-go][starlark-go] CLI and asserts they produce identical output.
To enable, install the Go implementation and make sure it's on `PATH`:

```sh
go install go.starlark.net/cmd/starlark@latest
```

[starlark-go]: https://github.com/google/starlark-go

## License

Apache 2.0.
See [`LICENSE`](LICENSE).

This is a derivative work: the lexer, parser, resolver, evaluator, and value model are ported from the Java reference implementation maintained by **The Bazel Authors** as part of [bazelbuild/bazel][bazel].
The conformance test files under [`conformance/`](conformance/) are copied verbatim from that
project.
[`docs/spec.md`](docs/spec.md) is fetched verbatim from [bazelbuild/starlark][starlark-spec] for reference.

[starlark-spec]: https://github.com/bazelbuild/starlark
