# Roadmap

Phases are ordered by dependency. Each phase calls out the relevant Java
sources under `reference/` and the conformance files in `conformance/` that
should start passing once the phase lands. The conformance file list is a
target, not a contract — many files exercise multiple phases and only flip to
passing in the phase that lands the *last* missing piece.

## Phase 1 — Lexer

Tokenize source into a stream of (kind, value, span). Includes Python-style
INDENT/OUTDENT/NEWLINE handling, string escapes (including raw and triple
strings), int/float literals, and the full keyword and operator set.

- Java: `syntax/Lexer.java`, `syntax/TokenKind.java`, `syntax/ParserInput.java`,
  `syntax/Location.java`, `syntax/FileLocations.java`.
- Python: `src/starlark/syntax/lexer.py`, `tokens.py`, `location.py`.
- Tests: `tests/test_lexer.py`. No conformance files yet.

## Phase 2 — Parser + AST

Recursive-descent parser producing an AST that mirrors `net.starlark.java.syntax`
node types. We omit the experimental Starlark type-syntax features
(`cast`, `isinstance` keyword, ellipsis, `->` return types) — Bazel's
`FileOptions` keeps them gated by default and the conformance suite doesn't
depend on them.

- Java: `syntax/Parser.java`, `syntax/Statement.java`, `syntax/Expression.java`,
  and the various `*Statement.java` / `*Expression.java` node classes.
- Python: `src/starlark/syntax/ast.py`, `parser.py`.
- Tests: `tests/test_parser.py`.

## Phase 3 — Resolver

Walks the AST, resolves identifiers, classifies them as Local / Cell / Free /
Global / Predeclared / Universal, and records function frame sizes. Converts
the file AST into a `Program` of resolved bindings.

- Java: `syntax/Resolver.java`, `syntax/Program.java`, `syntax/StarlarkFile.java`.
- Python: `src/starlark/syntax/resolver.py`, `program.py`.
- Tests: `tests/test_resolver.py`.

## Phase 4 — Value model + Mutability

Implement the runtime value taxonomy and the `Mutability` token that gates
mutation. `bool`, `int`, `float`, `str`, `NoneType`, `tuple`, `list`, `dict`,
`set`, `range`, `function`. Every mutable value carries a `Mutability`
reference and raises on mutation when frozen.

- Java: `eval/Mutability.java`, `eval/StarlarkValue.java`, `eval/StarlarkList.java`,
  `eval/Dict.java`, `eval/Tuple.java`, `eval/RangeList.java`, `eval/StarlarkSet.java`,
  `eval/StarlarkFloat.java`, `eval/NoneType.java`, `eval/Module.java`.
- Python: `src/starlark/eval/{values,mutability,module}.py`.
- Tests: `tests/test_values.py`.

## Phase 5 — Evaluator: statements

Tree-walking interpreter over statement nodes — assignments, augmented
assignments, `if`/`elif`/`else`, `for`, `while`, `pass`, `break`, `continue`,
`return`. Wires up `EvalException` with location/frame tracking.

- Java: `eval/Eval.java` (statement half), `eval/EvalException.java`,
  `eval/StarlarkThread.java`.
- Python: `src/starlark/eval/{evaluator,thread,errors}.py`.
- Conformance unlocks: `assign.star`, `loop.star`, `cycles.star` (after
  Phase 6 expressions also).

## Phase 6 — Evaluator: expressions

Evaluate expressions: literals, identifiers, binops, unary ops, `if`-expr,
comprehensions, `[]` / `.` / call, slicing, lambdas. Implement EvalUtils
arithmetic, comparison, indexing, truth.

- Java: `eval/Eval.java` (expression half), `eval/EvalUtils.java`.
- Python: `src/starlark/eval/evaluator.py` (continued).
- Conformance unlocks: `and_or_not.star`, `equality.star`, most expressions in
  every other file.

## Phase 7 — Core builtins

`len`, `type`, `range`, `print`, `repr`, `str`, `int`, `float`, `bool`, `list`,
`tuple`, `dict`, `set`, `enumerate`, `zip`, `reversed`, `sorted`, `min`, `max`,
`hasattr`, `getattr`, `dir`, `hash`, `all`, `any`. Plus the test-driver
predeclared functions used by the conformance files: `assert_`, `assert_eq`,
`assert_fails`, `freeze`, `struct`, `mutablestruct`, `int_mul_slow`.

The decorator `@starlark_method(name=..., parameters=[...])` lands here, plus
the dispatcher.

- Java: `eval/MethodLibrary.java`, `eval/Starlark.java`, the `@StarlarkMethod`
  annotation processor (we replace this with a runtime decorator).
  For the test predeclared functions: `reference/src/test/java/net/starlark/
  java/eval/ScriptTest.java`.
- Python: `src/starlark/eval/{builtins,annot}.py`.
- Conformance unlocks: `min_max.star`, `all_any.star`, `range.star`,
  `reversed.star`, `sorted.star`, `equality.star`, `tuple.star`,
  `int_constructor.star`, `int.star`.

## Phase 8 — String methods

`startswith`, `endswith`, `find`, `rfind`, `index`, `rindex`, `replace`,
`split`, `rsplit`, `splitlines`, `partition`, `rpartition`, `strip`, `lstrip`,
`rstrip`, `lower`, `upper`, `title`, `capitalize`, `count`, `format`,
`format_map`, `join`, `elems`, `codepoints`, `isalnum`, etc.

- Java: `eval/StringModule.java`, `eval/FormatParser.java`.
- Python: `src/starlark/eval/string_methods.py`.
- Conformance unlocks: `string_*.star` (8 files).

## Phase 9 — List / dict / tuple methods

`append`, `extend`, `insert`, `pop`, `remove`, `clear`, `index` for list;
`get`, `setdefault`, `update`, `pop`, `popitem`, `keys`, `values`, `items`,
`clear` for dict; tuple is immutable but exposes `count`/`index`. Set methods
follow the same pattern.

- Java: methods on `StarlarkList.java`, `Dict.java`, `Tuple.java`,
  `StarlarkSet.java`.
- Python: methods on the corresponding classes from Phase 4.
- Conformance unlocks: `list.star`, `list_mutation.star`, `list_slices.star`,
  `dict.star`, `set.star`.

## Phase 10 — Function calls, closures, *args/**kwargs

User-defined functions with positional and keyword parameters, defaults,
`*args`, `**kwargs`, `*` (kw-only marker), nested defs, free variable cells,
recursion check.

- Java: `eval/StarlarkFunction.java`, `eval/StarlarkCallable.java`,
  `eval/CallUtils.java`, `eval/ParamDescriptor.java`,
  `eval/MethodDescriptor.java`.
- Python: `src/starlark/eval/function.py`.
- Conformance unlocks: `function.star`, `comprehension.star`, `fields.star`.

## Phase 11 — load() statement

Parse `load(...)` calls, model module loading with a pluggable loader. Wire
it through to `Module` from Phase 4.

- Java: `syntax/LoadStatement.java`, the `load`/`thread.loadProgram` flow in
  `eval/StarlarkThread.java` and `Eval.java`.
- Python: `src/starlark/eval/loader.py`.
- Conformance unlocks: none in this set use `load()` directly, but it's a
  prerequisite for any extension to test in multi-file mode.

## Phase 12 — assert.star module (as needed)

The Bazel conformance suite uses **predeclared** assertion functions, not the
starlark-go-style `load("assert.star", "asserts")` form. Phase 7 already
provides those. This phase exists as a placeholder — if it turns out a
conformance file does need the load form, we ship an `assert.star` here
based on starlark-go's `starlarktest/assert.star`. Keep this phase open;
likely zero-cost.

## Phase 13 — Conformance suite turn-on

Wire `tests/test_conformance.py` to parameterize over `conformance/*.star`,
honoring the chunk separator `\n---\n` and the `### regex` error expectations
exactly as Bazel's `ScriptTest.java` does. Mark all xfail at the start of
this phase; flip them to xpass as features land. The pytest summary line
becomes the progress dashboard.

Also write `tests/test_cross_validation.py` that runs each `.star` file
through `starlark` (the starlark-go CLI) when it's on PATH and asserts
matching exit status and stdout. Skip cleanly if absent.

## Phase 14 — Cleanup, docs, README, zipapp

- Self-review every file. Names, error messages, dead code.
- `python -m zipapp src/starlark -o starlark.pyz -p '/usr/bin/env python3'`,
  smoke-test running the zipapp on a `.star` file.
- README: usage, divergences from the Java reference, build status.
- Tag a release. Stop or hand off.
