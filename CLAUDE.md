# CLAUDE.md

Orientation for future Claude sessions resuming this port. Read STATUS.md
*after* this for the current journal entry.

## What this repo is

A pure-Python tree-walking interpreter for the Starlark configuration
language. It is a port of Bazel's Java reference implementation.

The Java source from bazelbuild/bazel was kept under `reference/` during
the initial port; that directory has since been removed. If you need to
grep the Java reference, fetch it from
https://github.com/bazelbuild/bazel/tree/master/src/main/java/net/starlark/java
into a scratch checkout. The actual deliverable lives in `src/starlark/`.

## Architectural decisions (settled — DO NOT relitigate)

If you want to deviate, write a 3-paragraph analysis in STATUS.md under
"Decisions Pending" and continue on something else.

1. **Tree-walking interpreter.** Recursive evaluation over the AST, mirroring
   `net.starlark.java.eval.Eval`. No bytecode.
2. **Integers are Python `int`.** Drop the Java `StarlarkInt` int32/int64/
   BigInteger union. Python's int is arbitrary precision; that IS the model.
3. **Strings are Python `str`, indexed by code point.** Diverges from Java's
   UTF-16 indexing for non-BMP characters. Documented in README.
4. **Mutability is a per-Module token object.** Implement
   `net.starlark.java.eval.Mutability` as a Python class with a `frozen: bool`
   flag. Every mutable value (list, dict, struct) holds a reference. Mutating
   methods raise `EvalError` when frozen. `Module.freeze()` is O(1).
5. **Builtin registration via decorator.** `@starlark_method(name=..., parameters=[...])`
   stores metadata on the function. Use `inspect.signature` where it suffices.
6. **EvalException subclasses Exception.** Carries a list of (location,
   function-name) frames. Raised from eval; caught at the API boundary.
7. **`assert_eq` etc. are predeclared, not loaded.** The conformance `.star`
   files in this repo follow Bazel's `ScriptTest` convention — they call
   `assert_eq`/`assert_`/`assert_fails`/`freeze`/`struct`/`mutablestruct`/
   `int_mul_slow` as predeclared builtins. Phase 7 provides them. Phase 12
   (`assert.star` module load form) is a placeholder.

## Goals (settled)

- Zero non-stdlib runtime dependencies.
- CPython 3.11+.
- Runs as a zipapp.
- Passes `conformance/*.star`.
- **Performance is NOT a goal.** Choose simplicity over cleverness.

## Layout

    conformance/           38 .star test files copied verbatim from Bazel.
    src/starlark/
      __init__.py          Public API (eval(), parse(), etc.)
      syntax/              Mirrors net.starlark.java.syntax
        tokens.py          TokenKind + Token
        location.py        FileLocations + Position
        errors.py          SyntaxError
        lexer.py           Lexer (DONE)
        ast.py             AST node dataclasses (DONE)
        parser.py          Parser (DONE)
        resolver.py        Resolver (in progress)
      eval/                Mirrors net.starlark.java.eval (not started)
    tests/
      test_lexer.py        27 unit tests
      test_parser.py       32 unit tests
      test_lexer_conformance.py    38 .star files lex
      test_parser_conformance.py   38 .star files parse (chunk-split on '---')
      test_smoke.py        import check + xfail eval('1+1')
    ROADMAP.md             14 phases with Java references
    STATUS.md              Journal — newest entries on top
    pyproject.toml         hatchling, no runtime deps, pytest+ruff dev
    uv.lock                Pinned dev deps

## How to develop

1. `uv sync` once.
2. `uv run pytest -q` for the full suite.
3. `uv run pytest tests/test_X.py -q` per-phase.
4. `uv run ruff check --fix src tests` before committing.
5. **Commit per concept.** History should read like a tutorial. Use semantic
   messages: "Phase N: <what>." for phase landings.
6. **Every commit has a test delta.** Either a new passing test, an xfail
   flipping to xpass, or a new xfail with explanation.
7. **STATUS.md after every phase boundary.** Date, what landed, what's next,
   any Decisions Pending.

## Conformance tests

The 38 `.star` files come from Bazel's `ScriptTest`. Idioms:

- `\n---\n` separates **independent parse/eval chunks**. Each chunk is parsed
  and evaluated in its own context.
- `### regex` comments mark **expected error patterns** on that line.
- Predeclared functions used by the files: `assert_eq`, `assert_`,
  `assert_fails`, `freeze`, `struct`, `mutablestruct`, `int_mul_slow`.
- See Bazel's `net.starlark.java.eval.ScriptTest` for the canonical
  implementation of the test driver.

Phase 13 wires `tests/test_conformance.py` to parameterize over these files,
honoring chunks and expectations. Until then, they're parser/lexer smoke
tests only.

## Reference priority order

When unsure about an edge case:
1. https://github.com/bazelbuild/starlark/blob/master/spec.md
2. The Java reference at https://github.com/bazelbuild/bazel/tree/master/src/main/java/net/starlark/java
3. starlark-go's behavior (run via `starlark` CLI if available)
4. Ask the user.

## Stopping conditions

Stop and ask the user when:
- A Decision is Pending per the architectural rules.
- Conformance pass rate stops growing for two consecutive phases.
- Conformance pass rate exceeds 95%.

Do NOT stop because:
- A phase is hard. Read more reference code.
- A test fails. Fix it or xfail it with explanation.
- You're uncertain about a small detail. Pick the obvious option, document it
  in STATUS.md, move on.

## Branch and push

- Branch: `claude/starlark-java-to-python-S9D2u`. Stay on it.
- Force-push is fine — the branch is yours.
- Do NOT create pull requests unless the user explicitly asks.
- Do NOT push to other branches.
