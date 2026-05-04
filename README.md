# starlark-python

Pure-Python tree-walking interpreter for the [Starlark][spec] configuration
language. This is a port of the Java reference implementation that ships with
[Bazel][bazel].

[spec]: https://github.com/bazelbuild/starlark/blob/master/spec.md
[bazel]: https://github.com/bazelbuild/bazel

## Status

Early. Tracking progress in [`STATUS.md`](STATUS.md). The plan is in
[`ROADMAP.md`](ROADMAP.md).

## Goals

- Zero non-stdlib runtime dependencies.
- CPython 3.11+.
- Runs as a zipapp.
- Passes the conformance suite copied verbatim from Bazel into
  [`conformance/`](conformance/).

Performance is **not** a goal. Correctness, clarity, and zero deps are.

## Documented divergences from the Java reference

These are intentional and not bugs:

- **Integers are `int`.** Python's arbitrary-precision integer is the model.
  There is no overflow.
- **Strings are indexed by Unicode code point.** The Java reference indexes by
  UTF-16 code unit, which has surprising behavior on non-BMP characters. The
  spec leaves this implementation-defined.

## Layout

    reference/    Java source from bazelbuild/bazel, kept for reference.
    conformance/  .star conformance tests, copied verbatim from Bazel.
    src/starlark/ The actual port.
    tests/        Python tests for the port.

## License

Apache 2.0. See [`LICENSE`](LICENSE).
