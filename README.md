# starlark-python

Pure-Python tree-walking interpreter for the [Starlark][spec] configuration
language. Ported from the Java reference implementation that ships with
[Bazel][bazel].

[spec]: https://github.com/bazelbuild/starlark/blob/master/spec.md
[bazel]: https://github.com/bazelbuild/bazel

## Status

26 of 38 conformance test files passing (68%); the remaining 12 are tracked
in `tests/test_conformance.py` under `XFAIL_FILES`. See [`STATUS.md`](STATUS.md)
for the journal and [`ROADMAP.md`](ROADMAP.md) for the implementation plan.

## Goals

- Zero non-stdlib runtime dependencies.
- CPython 3.11+.
- Runs as a single-file zipapp.
- Passes the conformance suite copied verbatim from Bazel into
  [`conformance/`](conformance/).

Performance is **not** a goal. Correctness, clarity, and zero deps are.

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

## CLI

The package installs a `starlark-python` console script. (We picked the
suffixed name so it doesn't shadow `starlark` from go.starlark.net, which
we use for cross-validation.) It can also be run as a zipapp:

```sh
make zipapp                              # builds ./starlark-python.pyz (~560K)
./starlark-python.pyz -c "1 + 2 * 3"     # 7
./starlark-python.pyz path/to/script.star
```

## load() and the host API

The runtime does not load files itself; the host supplies a `Loader`
callable. `eval/loader.py` ships a simple file-based loader you can plug in:

```python
from starlark.eval.loader import FileLoader
import starlark

loader = FileLoader(exec_file=starlark.exec_file, search_paths=[".", "lib"])
starlark.exec_file(open("main.star").read(), loader=loader)
```

`load("foo.star", "bar")` then resolves `foo.star` against `loader`.

## Documented divergences from the Java reference

These are intentional, not bugs:

- **Integers are Python `int`.** Arbitrary precision; no overflow. The Java
  reference uses a `StarlarkInt` union of int32 / int64 / BigInteger.
- **Strings are indexed by Unicode code point.** The Java reference indexes
  by UTF-16 code unit, which produces surprising results for non-BMP
  characters. The spec leaves this implementation-defined.
- **No 32-bit range checks for `range()`, `*` repeat, etc.** The Java
  reference rejects allocations whose length doesn't fit in a signed 32-bit
  int. We instead cap container allocations at 16M elements with a less
  specific error message.

The conformance suite includes a handful of tests that depend on the Java
reference's exact error wording for these checks; they are listed in
`XFAIL_FILES` in `tests/test_conformance.py`.

## Layout

    conformance/  .star conformance tests, copied verbatim from Bazel.
    src/starlark/ The actual port.
      syntax/     lexer, parser, AST, resolver
      eval/       value model, evaluator, builtins, methods, loader
      cmd.py      CLI entry point
    tests/        Pytest suite (unit + conformance).
    STATUS.md     Implementation journal.
    ROADMAP.md    14-phase implementation plan.

## Development

```sh
uv sync           # install deps
make test         # ~400 tests, ~2s
make lint         # ruff
make typecheck    # pyright
make zipapp       # build ./starlark-python.pyz
```

`tests/test_cross_validation.py` runs a curated set of programs under
both this interpreter and the [starlark-go][starlark-go] CLI and asserts
they produce identical output. To enable, install the go reference and
make sure it's on `PATH`:

```sh
go install go.starlark.net/cmd/starlark@latest
```

[starlark-go]: https://github.com/google/starlark-go

## License

Apache 2.0. See [`LICENSE`](LICENSE).

This is a derivative work: the lexer, parser, resolver, evaluator, and value
model are ported from the Java reference implementation maintained by **The
Bazel Authors** as part of [bazelbuild/bazel][bazel]. The conformance test
files under [`conformance/`](conformance/) are copied verbatim from that
project. [`docs/spec.md`](docs/spec.md) is fetched verbatim from
[bazelbuild/starlark][starlark-spec] for offline reference. The original
Apache-2.0 copyright and license terms apply to all derived material.

[starlark-spec]: https://github.com/bazelbuild/starlark
