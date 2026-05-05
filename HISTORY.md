# History

How this implementation came together: the original plan (the 14 phases
scoped at bootstrap) followed by the journal of what actually shipped,
newest entry first.

## Original plan

The 14 phases below were scoped at the start of the port. They were ordered
by dependency and called out the relevant Java sources under `reference/`
and the conformance files in `conformance/` that should start passing once
each phase landed. (`reference/` has since been removed; see the journal
entry for that day for the rationale.)

The conformance file list was a target, not a contract — many files
exercised multiple phases and only flipped to passing when the *last*
missing piece arrived.

### Phase 1 — Lexer

Tokenize source into a stream of (kind, value, span). Includes Python-style
INDENT/OUTDENT/NEWLINE handling, string escapes (raw and triple strings),
int/float literals, and the full keyword and operator set.

- Java refs: `syntax/Lexer.java`, `syntax/TokenKind.java`,
  `syntax/ParserInput.java`, `syntax/Location.java`,
  `syntax/FileLocations.java`.
- Python: `src/starlark/syntax/lexer.py`, `tokens.py`, `location.py`.
- Tests: `tests/test_lexer.py`. No conformance files yet.

### Phase 2 — Parser + AST

Recursive-descent parser producing an AST that mirrors
`net.starlark.java.syntax`. We omit the experimental Starlark type-syntax
features (`cast`, `isinstance` keyword, ellipsis, `->` return types) —
Bazel's `FileOptions` keeps them gated by default and the conformance
suite doesn't depend on them.

- Java refs: `syntax/Parser.java`, `syntax/Statement.java`,
  `syntax/Expression.java`, and the various `*Statement.java` /
  `*Expression.java` node classes.
- Python: `src/starlark/syntax/ast.py`, `parser.py`.
- Tests: `tests/test_parser.py`.

### Phase 3 — Resolver

Walks the AST, resolves identifiers, classifies them as Local / Cell /
Free / Global / Predeclared / Universal, and records function frame sizes.
Converts the file AST into a `Program` of resolved bindings.

- Java refs: `syntax/Resolver.java`, `syntax/Program.java`,
  `syntax/StarlarkFile.java`.
- Python: `src/starlark/syntax/resolver.py`.
- Tests: `tests/test_resolver.py`.

### Phase 4 — Value model + Mutability

Implement the runtime value taxonomy and the `Mutability` token that gates
mutation. `bool`, `int`, `float`, `str`, `NoneType`, `tuple`, `list`,
`dict`, `set`, `range`, `function`. Every mutable value carries a
`Mutability` reference and raises on mutation when frozen.

- Java refs: `eval/Mutability.java`, `eval/StarlarkValue.java`,
  `eval/StarlarkList.java`, `eval/Dict.java`, `eval/Tuple.java`,
  `eval/RangeList.java`, `eval/StarlarkSet.java`, `eval/StarlarkFloat.java`,
  `eval/NoneType.java`, `eval/Module.java`.
- Python: `src/starlark/eval/{values,mutability,module}.py`.
- Tests: `tests/test_values.py`.

### Phase 5 — Evaluator: statements

Tree-walking interpreter over statement nodes — assignments, augmented
assignments, `if`/`elif`/`else`, `for`, `pass`, `break`, `continue`,
`return`. Wires up `EvalException` with location/frame tracking. (`while`
is forbidden by the spec and rejected at parse time.)

- Java refs: `eval/Eval.java` (statement half), `eval/EvalException.java`,
  `eval/StarlarkThread.java`.
- Python: `src/starlark/eval/{evaluator,errors}.py`.

### Phase 6 — Evaluator: expressions

Evaluate expressions: literals, identifiers, binops, unary ops, `if`-expr,
comprehensions, `[]` / `.` / call, slicing, lambdas. Implement EvalUtils
arithmetic, comparison, indexing, truth.

- Java refs: `eval/Eval.java` (expression half), `eval/EvalUtils.java`.
- Python: `src/starlark/eval/evaluator.py` (continued).
- Conformance unlocks: `and_or_not.star`, `equality.star`, most expressions
  in every other file.

### Phase 7 — Core builtins

`len`, `type`, `range`, `print`, `repr`, `str`, `int`, `float`, `bool`,
`list`, `tuple`, `dict`, `set`, `enumerate`, `zip`, `reversed`, `sorted`,
`min`, `max`, `hasattr`, `getattr`, `dir`, `hash`, `all`, `any`, `sum`,
`fail`, `abs`. Plus the test-driver predeclared functions used by the
conformance files: `assert_`, `assert_eq`, `assert_fails`, `freeze`,
`struct`, `mutablestruct`, `int_mul_slow`.

- Java refs: `eval/MethodLibrary.java`, `eval/Starlark.java`. For the test
  predeclared functions: `eval/ScriptTest.java`.
- Python: `src/starlark/eval/{builtins,test_driver}.py`.

### Phase 8 — String methods

`startswith`, `endswith`, `find`, `rfind`, `index`, `rindex`, `replace`,
`split`, `rsplit`, `splitlines`, `partition`, `rpartition`, `strip`,
`lstrip`, `rstrip`, `lower`, `upper`, `title`, `capitalize`, `count`,
`format`, `join`, `elems`, `removeprefix`, `removesuffix`, `isalnum` and
the rest of the `is*` predicates.

- Java refs: `eval/StringModule.java`, `eval/FormatParser.java`.
- Python: `src/starlark/eval/string_methods.py`.

### Phase 9 — List / dict / set methods

`append`, `extend`, `insert`, `pop`, `remove`, `clear`, `index`, `count`
for list; `get`, `setdefault`, `update`, `pop`, `popitem`, `keys`,
`values`, `items`, `clear` for dict; `add`, `discard`, `remove`, `clear`,
`update`, `pop`, `union`, `intersection`, `difference`,
`symmetric_difference`, the `_update` variants, `isdisjoint`, `issubset`,
`issuperset` for set.

- Java refs: methods on `StarlarkList.java`, `Dict.java`, `Tuple.java`,
  `StarlarkSet.java`.
- Python: `src/starlark/eval/collection_methods.py`.

### Phase 10 — Function calls, closures, *args/**kwargs

User-defined functions with positional and keyword parameters, defaults,
`*args`, `**kwargs`, `*` (kw-only marker), nested defs, free variable
cells, recursion check.

- Java refs: `eval/StarlarkFunction.java`, `eval/StarlarkCallable.java`,
  `eval/CallUtils.java`.
- Python: `src/starlark/eval/function.py`.

### Phase 11 — `load()` statement

Parse `load(...)` calls, model module loading with a pluggable loader.
Wire it through to `Module` from Phase 4.

- Java refs: `syntax/LoadStatement.java`, the `load` flow in
  `eval/StarlarkThread.java` and `Eval.java`.
- Python: `src/starlark/eval/loader.py`.

### Phase 12 — assert.star module (placeholder)

The Bazel conformance suite uses **predeclared** assertion functions, not
the starlark-go-style `load("assert.star", "asserts")` form. Phase 7
already provides those. This phase exists as a placeholder — if it turns
out a conformance file does need the load form, ship an `assert.star`
based on starlark-go's `starlarktest/assert.star`.

### Phase 13 — Conformance suite turn-on

Wire `tests/test_conformance.py` to parameterize over `conformance/*.star`,
honoring the chunk separator `\n---\n` and the `### regex` error
expectations exactly as Bazel's `ScriptTest.java` does. Mark files xfail
initially; flip to xpass as features land.

Also write `tests/test_cross_validation.py` that runs each `.star` file
through `starlark` (the starlark-go CLI) when it's on PATH and asserts
matching exit status and stdout. Skip cleanly if absent.

### Phase 14 — Cleanup, docs, README, zipapp

- Self-review every file. Names, error messages, dead code.
- `python -m zipapp src/starlark -o starlark-python.pyz`,
  smoke-test running the zipapp on a `.star` file.
- README: usage, divergences from the Java reference, build status.

---

## Journal

Append-only. Newest entries on top.

### 2026-05-04 — HISTORY.md consolidation

Merged the previous `ROADMAP.md` (the original phase plan) and `STATUS.md`
(the journal) into this single file: plan above, journal below. The two
were always read together and kept drifting; one file is easier to keep
truthful.

`README.md`, `CLAUDE.md`, and the in-tree layout doc all point to
`HISTORY.md` now. No code changes; tests still 426 passed, 4 xfailed.

### 2026-05-04 — Spec-compliance push: 26/38 → 34/38 conformance

Acted on the xfail review: landed every "real spec bug" plus most of the
mechanical wording alignment. The 4 remaining xfails are all documented
divergences from the Java reference that we decided to keep:

| File | Reason |
| --- | --- |
| `range.star` | Java's signed-32-bit `range()` argument check; we use arbitrary-precision `int`. |
| `json.star` | Java UTF-16 indexing for surrogate halves (`"😹"[:1]`). |
| `sorted.star` | Non-BMP string ordering depends on UTF-16 code-unit order. |
| `fields.star` | `mutablestruct` test helper rejects type-changing reassignment — Bazel-specific, not in spec. |

Real spec fixes:

- `_bitwise()` error message hardcoded `|` (so `1 & False` reported
  "int | bool"). Now uses the actual operator.
- `str.format` rejects `,`/`.`/`[`/`]` in field names with the spec's
  *"Invalid character X inside replacement field"*; detects *"Cannot mix
  manual and automatic numbering"* between `{}` and `{N}`; `{-N}` parses
  as out-of-range positional index, not keyword.
- `str.replace`, `removeprefix`, `removesuffix` reject non-string args
  with `got value of type X, want string` /
  `parameter count got value of type NoneType, want int`.
- **Strings are not iterable per the spec.** `for c in "abc"` and
  `enumerate("ab")` now reject; use `.elems()` instead.
- Recursion check switched from `id(StarlarkFunction)` to `id(ast_node)`,
  so two closures from the same `lambda` count as the same function and
  Y-combinator patterns are properly rejected.
- `freeze()` with no arguments freezes the current `Module`'s
  `Mutability`.
- Comparison error format: `<=>` (not `<`); operand order preserved (no
  longer alphabetized).
- `min(int, str)` reports operands in (running-best, candidate) order to
  match Java.
- `json.encode(set(...))` works (matches starlark-go).
- Python `TypeError` from builtin arg-binding is now translated to a
  cleaner `EvalError` (`missing 1 required positional argument: key`).
- `json` depth limit message changed to *"nesting depth limit exceeded"*
  and the encoder also enforces it.
- Tuple/list unpacking errors: *"got 'X' in sequence assignment (want
  N-element sequence)"* / *"too few values to unpack (got X, want Y)"* /
  *"too many values to unpack ..."*.
- NaN as dict/set key is normalized to a singleton so
  `d[float("nan")] = v` updates the existing entry. NaN equals NaN at the
  value-model level (matches Java/Go).
- `1 // -inf == -0.0` (mathematical floor, matches Java/Go).
- Augmented set ops mutate in place: `s |= other`, `s &= other`,
  `s -= other`, `s ^= other`. Same for `d |= other`.
- `set` rounded out: `update`, `pop`, `intersection_update`,
  `difference_update`, `symmetric_difference`, `symmetric_difference_update`,
  `isdisjoint`. `set()` and `dict()` positional-arg cap message:
  *"accepts no more than 1 positional argument"*.

Wording alignment for byte-equivalence with Bazel:

- `int()` rebuilt: full set of base/prefix rules, leading-zero rejection,
  whitespace rejection, error messages match Bazel exactly.
- `float()` error wording (overflow, invalid literal).
- `%d` / `%x` / `%o` / `%g` / `%f` format errors:
  *"got X for '%d' format, want int or float"*.
- Integer division errors say *"integer division by zero"* regardless of
  operand types (only true division switches to *"floating-point"*).
- Various index/slice/range/key error messages match Bazel's wording.

Float repr/format overhaul:

- `_float_repr` now uses `repr(x)` as the basis (shortest round-trip,
  same as Java's `Double.toString`); for values in Java's "fixed range"
  `[1e-3, 1e17)` where Python's repr switches to scientific too early,
  fall back to `Decimal(repr(x))` and format fixed.
- `%f` uses `Decimal(repr(x))` for the same reason: `"%f" % 1.23e45`
  produces the shortest-round-trip digits, not Python's exact-binary
  representation.
- `%g` defers to `_float_repr` so `str(x)` and `"%g" % x` agree.

Tests: 426 passed (up from 423), 4 xfailed. Cross-validation against
starlark-go still 23/23 green.

Removes `docs/xfail-review.md`, which is now stale.

### 2026-05-04 — Cross-validation against starlark-go (full path)

Replaced the conformance-file-based cross-validation (which couldn't run
under starlark-go because the `.star` files use Bazel `ScriptTest`'s
predeclared `assert_eq`/etc.) with a curated set of 23 short Starlark
programs that exercise arithmetic, comparisons, strings, lists, dicts,
tuples, control flow, def/lambda/closure, comprehensions, json round-trip,
sorted/min/max/len/type/bool/in. Both implementations are asserted to
produce **byte-for-byte identical stderr+stdout**.

Two follow-on changes were needed to get the streams to line up:

1. `b_print` writes to stderr (with a trailing newline default) to match
   both the Java and Go references' Starlark `print` semantics. Required
   renaming our CLI to `starlark-python` so it doesn't shadow the go
   binary, and is incidentally more correct: Starlark's `print()` is a
   diagnostic, not a result.
2. Go starlark CLI is invoked with `-globalreassign` so it allows
   top-level `if`/`for` (otherwise it applies BUILD-mode restrictions
   that don't apply to our permissive default).

### 2026-05-04 — pyright + ruff strict, json module, docs polish

- Pinned `pyright==1.1.409`, added `py.typed` markers, fixed type
  annotations end-to-end. `_is_int` / `_is_num` use `TypeGuard` for
  narrowing; `Identifier.binding: Binding | None` (was `object | None`);
  `Comprehension.body: Expression | DictEntry`. Tests gained explicit
  isinstance assertions where pyright couldn't narrow on its own.
- Pinned `ruff>=0.15,<0.16`. Fixed all new lints (B905 `zip()` strict,
  UP037 quoted annotations, RUF005 list concatenation, RUF043
  `pytest.raises(match=)` raw strings).
- Implemented the `json` module: `encode` / `decode` / `encode_indent` /
  `indent`. Hand-rolled — not Python's stdlib — so we control output
  format and error messages. Decoder caps depth at 256; rejects strict-
  JSON violations (leading zeros, control chars, dangling escapes,
  unpaired surrogates, trailing data).
- Added `docs/README.md` (developer tour) and `docs/spec.md` (the
  Starlark language spec, fetched verbatim from `bazelbuild/starlark`).
- Removed `reference/` (Java source from `bazelbuild/bazel`); ~2.6 MB
  trimmed. Anyone who needs to grep can fetch upstream.
- Credited The Bazel Authors in the README license section.

Conformance status at this point: 26/38 passing.

### 2026-05-04 — Phases 11, 12, 14 (load, packaging, polish)

What landed:

- **Phase 11 — `load()` statement.** `eval/loader.py` defines a `Loader`
  protocol (just `Callable[[str], Module]`) plus a `FileLoader` helper
  for the common case of loading from disk. `Thread.loader` carries it;
  the evaluator's `LoadStatement` handler injects the resolved bindings
  into the module's globals. 4 unit tests including a chained two-level
  load.
- **Phase 12 — assert.star module.** Placeholder per the original notes.
  The conformance suite uses predeclared `assert_eq`/etc. directly
  (Bazel `ScriptTest` style), which we ship via `eval/test_driver.py`.
  The starlark-go-style `load("assert.star", "asserts")` form is unused;
  if a future test file needs it, add `conformance/assert.star`.
- **Phase 14 — README, zipapp, CLI, cross-validation.**
  - `src/starlark/cmd.py` + `__main__.py`: `python -m starlark` or the
    `starlark-python` console script. Supports `-c EXPR`, a script path,
    and a minimal REPL.
  - `Makefile` with `test`, `lint`, `typecheck`, `fmt`, `zipapp`,
    `clean` targets. `make zipapp` produces a 560 KB self-contained
    `./starlark-python.pyz`.
  - `tests/test_cross_validation.py`: runs three known-good conformance
    files under both implementations and asserts matching exit status.
    Skips cleanly when the binary is absent.

### 2026-05-04 — Phases 1-13 (most of conformance suite passing)

Big push. All phases through 13 implemented; conformance dashboard at
**23 passing / 14 xfail / 1 skip** out of 38 files (60% pass rate).

What landed:

- **Phase 1 — Lexer.** `tokens.py`, `location.py`, `errors.py`,
  `lexer.py`. 27 unit tests + 38 conformance files lex cleanly.
- **Phase 2 — Parser + AST.** `ast.py` (dataclass nodes), `parser.py`.
  32 unit tests + 38 conformance files parse cleanly when chunk-split
  on `\n---\n`.
- **Phase 3 — Resolver.** `resolver.py`. Classifies every Identifier
  into LOCAL / FREE / GLOBAL / PREDECLARED / UNIVERSAL; per-function
  locals + free vars; basic structural validation. 12 unit tests.
- **Phase 4 — Value model + Mutability.** `values.py`, `mutability.py`,
  `module.py`, `errors.py`. Native Python `bool`/`int`/`float`/`str`/
  `tuple` used directly; mutable wrappers `StarlarkList` / `Dict` /
  `StarlarkSet` carry a `Mutability` ref; `Range` is immutable lazy.
  `BuiltinFunction` wraps Python callables. 57 unit tests.
- **Phases 5+6 — Evaluator (statements + expressions).** `evaluator.py`.
  Tree-walking dispatch. All control-flow constructs, comprehensions
  (incl. dict comp), unpacking, augmented assignment with in-place
  list `+=`. Recursion forbidden per spec. 39 unit tests.
- **Phase 7 — Core builtins.** `builtins.py` + `test_driver.py` for
  the conformance helpers (`assert_eq`, `assert_`, `assert_fails`,
  `freeze`, `struct`, `mutablestruct`, `int_mul_slow`). Universal
  namespace with `len`, `range`, `print`, `sorted` (lambda-key OK via
  thread-context call-back), etc. 25 unit tests.
- **Phases 8+9 — String + collection methods.** `string_methods.py`,
  `collection_methods.py`. Full string method set; full list/dict/set
  method set; methods register via the per-type tables in `methods.py`.
  25 unit tests.
- **Phase 13 — Conformance suite turn-on.** `tests/test_conformance.py`
  parameterizes over `conformance/*.star`, splits chunks on `\n---\n`,
  honors `### regex` error expectations the same way Bazel's
  `ScriptTest` does. Files known to need more work are listed in
  `XFAIL_FILES`; trim the list as we land features.

### 2026-05-04 — Bootstrap complete

What landed:

- Pruned the fork: deleted everything Bazel-specific. Java sources moved
  to `reference/`, `.star` conformance files copied to `conformance/`.
  History squashed to a single orphan commit; `.git` shrunk from ~30M
  to ~700K.
- `pyproject.toml` with hatchling backend, no runtime deps, `pytest` and
  `ruff` as dev deps.
- `ROADMAP.md` with 14 phases, Java references, and conformance unlocks.
- `README.md` calling out the two intentional divergences (Python `int`
  for arbitrary precision, code-point string indexing).

Notes / clarifications:

- The conformance `.star` files in this repo are written for Bazel's
  `ScriptTest`, which **predeclares** `assert_eq`/etc. as builtins.
  They do **not** use `load("assert.star", "asserts")` like
  starlark-go's testdata.
- Bazel-only token kinds (doc comments, type-syntax extras) skipped.

## Decisions Pending

(none)
