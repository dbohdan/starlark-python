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

### 2026-05-07 — Host integration API (Phase 4: namespace helper)

Added `starlark.namespace(name, fields)`, which builds the
`fields` dict + `_starlark_type` object protocol that the evaluator
already consumes for `json.*` and the conformance test driver's
`Struct`. Hosts no longer have to hand-roll the protocol the way
remarshal did with its private `_Module` class.

Two ergonomics: Python callables in `fields` are auto-wrapped as
`BuiltinFunction(name=f"{namespace}.{key}", impl=fn)` so attribute
access and error messages have qualified names; non-callable values
(strings, ints, anything) are stored verbatim, so a configuration
namespace like `namespace("config", {"version": "1.0"})` just works.
Pre-wrapped `BuiltinFunction` values pass through unchanged.

The internal `json_module._JsonModule` and `test_driver.Struct`
classes are NOT refactored to use `namespace()` in this phase. Both
have additional behavior (frozen / mutable variants, equality
semantics) beyond what `namespace()` covers, and the goal here is the
public API, not internal cleanup.

14 tests in `tests/test_namespace.py` cover construction, callable
auto-wrapping, attribute access from Starlark, json round-trip
(`json.encode(ns)` works because the encoder honors `fields`), and a
full end-to-end simulation of remarshal's helper-module pattern.

This completes the four-phase host integration rollout. Next: README.

### 2026-05-07 — Host integration API (Phase 3: compile-once Program API)

The big one. Added `starlark.compile(source) → Program`, with
`Program.eval()` for expressions and `Program.exec()` for files.
A `Program` parses the source once and can be invoked many times
against fresh `Module`s — exactly the shape remarshal needs for its
"one transform, many docs" pipeline.

`compile(source, mode=...)` takes a `mode=` kwarg: `"auto"` (default)
classifies expression-vs-file by trying expression-parse first;
`"expression"` forces expression form; `"file"` forces file form.
The `mode="file"` override matters: a single-line `do_something()`
parses as a valid expression but the host usually means "run this as
a one-statement file". `exec_file()` uses `mode="file"` internally
so the conformance suite's `assert_eq(...)` chunks still work.

Resolution is redone on every `.eval()`/`.exec()` call. The resolver
mutates the AST in place (overwrites `Identifier.binding`,
`DefStatement.locals`, `StarlarkFile.globals`) but never accumulates
state, so re-resolving with a different env is safe. Performance is
not a goal — re-resolve is cheap relative to evaluation, and the
caching design space is not worth opening.

The previous `eval()` implementation built a synthesised
`StarlarkFile` wrapping the parsed `Expression`, called the resolver
on it, then bypassed `eval_file` and called the private `_eval_expr`.
That dance is now gone — `Program` does the same thing once, cleanly,
and the top-level `eval()`/`exec_file()` are five-line wrappers over
`compile(...).eval()` / `compile(..., mode="file").exec()`.

18 tests in `tests/test_compile.py` cover auto-detection, mode
overrides, repeat-execution with fresh state, mismatched call shape,
per-run resource limits, and a full simulated remarshal-pattern
round-trip using only the public API (no `starlark.eval.*` imports).

### 2026-05-07 — Host integration API (Phase 2: parse error consistency)

The top-level `parse(source)` and `parse_expression(source)` functions
now raise `StarlarkSyntaxException` on lex or parse errors. Previously
`parse` returned a `StarlarkFile` with errors collected in `.errors`
and `parse_expression` raised a plain `ValueError` on lex errors —
three different shapes for the same kind of failure, which forced
remarshal to catch all three.

The lower-level `Parser` class methods (`Parser(lexer).parse_file()`,
`Parser(lexer).parse_expression()`) keep the error-list shape — they
remain the building block for error-recovery tooling and IDE
integrations. The top-level functions are thin "raise on error"
wrappers around them.

This is a behavior change for callers that constructed a parse, then
inspected `.errors` to decide what to do. The two in-repo affected
test files (`test_parser.py`, conformance `parse_to_completion`)
either switched to `Parser(...).parse_file()` for error inspection or
relied on the new raising behavior implicitly. The project is at 0.x
and there is no out-of-tree consumer that depends on the old shape.

10 new tests in `tests/test_parse_errors.py` cover the raising
behavior and the lower-level escape hatch.

### 2026-05-07 — Host integration API (Phase 1: re-exports + conversion helpers)

A downstream user of this library
([remarshal](https://github.com/dbohdan/remarshal/blob/dev/src/remarshal/starlark_transform.py))
had to reach into `starlark.eval.values`, `starlark.eval.module`, and
`starlark.syntax.errors` and read `value._data` to wire Starlark into
their data-transformation pipeline. The settled architectural decisions
(integers are Python `int`, strings are Python `str`, mutability is a
per-Module token) are exactly right for this use case — the awkwardness
was just a missing public surface. Four-phase rollout begins; this is
phase one.

**What landed.** New `starlark.values` submodule (mirrors the
`net.starlark.java.eval` layout) with public re-exports of `Dict`,
`StarlarkList`, `StarlarkSet`, `Range`, `BuiltinFunction`, `Mutability`,
`IMMUTABLE`, plus `to_value` / `from_value` / `UnsupportedTypeError`.
Top-level `starlark` re-exports the headline names so
`from starlark import to_value, Dict, Mutability` works. `SyntaxError`
(the `syntax.errors` dataclass) is re-exported as `StarlarkSyntaxError`
to avoid shadowing the Python builtin on `from starlark import *`;
`StarlarkSyntaxException` (the raisable form) is now exported too.

**Conversion semantics.** `to_value` recursively wraps `dict`/`list` as
`Dict`/`StarlarkList` and leaves `tuple` as `tuple` (Starlark's tuple is
the Python tuple). Scalars (`None`, `bool`, `int`, `float`, `str`,
`bytes`, `datetime` types) pass through. Default `mutability=` is a
fresh `Mutability("to_value")` that's frozen after construction — the
common case is "I just want to pass data in", and a frozen tree is the
safe default. Callers wanting Starlark code to mutate the input pass
`module.mutability` explicitly. `from_value` is intentionally
container-lossy: `Dict→dict`, `StarlarkList→list`, `Range→list`,
`tuple→list`. Sets raise `UnsupportedTypeError` with a hint to call
`sorted(s)` or `list(s)` in Starlark first.

**What's next.** Phase 2 makes `parse` and `parse_expression` raise
`StarlarkSyntaxException` consistently (they currently differ — `parse`
returns errors via `file.errors`, `parse_expression` raises `ValueError`
on lex errors). Phase 3 adds `compile(source) → Program` with
`.eval()`/`.exec()` so hosts can parse-and-resolve once and run the
program many times against fresh modules. Phase 4 adds a
`namespace(name, fields)` helper for the
"`fields` dict + `_starlark_type`" object protocol that
`json_module._JsonModule` and `test_driver.Struct` already implement.
README gets a Host Integration section once all four land.

### 2026-05-05 — Thread safety, step counter, charge-only heap counter

Acted on the threat-model gap the security reviewers flagged. Four
phases, each its own commit:

**Phase A — thread safety.** Replaced the three module-level stacks
(`_CURRENT_THREAD` and `_CURRENT_MUTABILITY` in `eval/builtins.py`,
`_REPORTERS` in `eval/test_driver.py`) with `contextvars.ContextVar`s.
Each OS thread sees its own context, so two host threads can call
`exec_file` concurrently without stomping on each other; nesting
within one thread uses `Token` save/restore. Originally estimated as
1–2 days of mechanical work threading an explicit `Thread` parameter
through ~150 builtin signatures; the `ContextVar` rewrite cut that to
~30 lines and an hour. Eight tests in `tests/test_thread_safety.py`
cover parallel `exec_file`, parallel `sorted(key=fn)` callbacks,
parallel `freeze()`, reporter isolation, nested `exec_file` within a
thread, and stress sweeps at 2/4/8 workers.

**Phase B — step counter.** Added `Thread.steps`, `Thread.max_steps`,
`Thread.on_max_steps`, and a `tick()` method. Charged at the top of
every statement (`_exec_stmt`), every expression node (`_eval_expr`),
and every `call()` invocation. New `StepLimitExceeded` subclasses a
new `ResourceLimitExceeded` (which subclasses `EvalError`), so hosts
can catch DoS-style aborts as a single category. The `on_max_*`
callbacks are go-style: invoked once before the raise; can pre-empt
the default raise with a custom exception. Eleven tests; the unit is
intentionally coarse and matches starlark-java's documented choice.

**Phase C — charge-only heap counter.** Added `Thread.allocs`,
`Thread.max_allocs`, `Thread.on_max_allocs`, and `add_allocs()`.
Charged in every container constructor (list / dict / set / range),
every mutating `append`/`extend`/`update`/`add`, and every `+`/`*`
that produces a new container or string. Sizes are approximate
constants in `eval/limits.py`, calibrated from `sys.getsizeof` on
64-bit CPython 3.11 and rounded. The counter is **charge-only**: no
refund on GC, so it bounds *cumulative allocation* rather than
*live memory*. Hosts size `max_allocs` at 2–4× the expected
steady-state working set. Nineteen tests; new `AllocLimitExceeded`
subclasses `ResourceLimitExceeded`.

I considered high-water tracking via `weakref.finalize` and rejected
it: GC timing makes the bound non-deterministic, cycles defeat
refcount release, native containers (str/tuple) can't accept
weakrefs, and every new wrapper type would have to think about the
finalize protocol. Charge-only has none of these costs and bounds the
worst-case DoS pattern just as well; the trade-off is documented in
`security/cost-estimates.md`.

**Phase D — docs.** Rewrote `security/threat-model.md` to document
the new opt-in API; rewrote `security/cost-estimates.md` as a
retrospective comparing estimate to actual; attached `Module.thread`
so hosts can read `module.thread.steps`/`.allocs` after a successful
run. Linked the threat model from the root `README.md` and added a
"Resource limits" section to `docs/README.md`.

API mirrors starlark-go closest: cap-style with optional `on_max_*`
callback (None = unlimited default), counters as public monotonic
fields. Errors form the `EvalError` ← `ResourceLimitExceeded` ←
{`StepLimitExceeded`, `AllocLimitExceeded`} hierarchy.

The threat-model rewrite also separates "DoS-style malicious values"
(which we mitigate) from "deliberate misconfiguration" (which no
config format can defend against — the host is responsible for
parsing freeform output into validated structs). Earlier wording
conflated the two and oversold what an interpreter alone can do.

494 passed (up from 455), 4 xfailed. Pyright clean, ruff clean.

#### Implementation notes: thread-safety and resource limits

Previously `security/cost-estimates.md`.

These were the largest items left after the small fixes (sandbox-boundary
test, centralized size cap, depth caps) landed. This document records
what was done, what it actually cost, and what the remaining options are
if the host needs stricter bounds than the implemented charge-only model
provides.

##### Phase A — thread-safety

###### What was done

Replaced the three module-level stacks
(`_CURRENT_THREAD`, `_CURRENT_MUTABILITY` in `eval/builtins.py`;
`_REPORTERS` in `eval/test_driver.py`) with `contextvars.ContextVar`s.
`ContextVar` isolates state per OS thread and per asyncio task, so two
host threads can call `starlark.exec_file` concurrently without
stomping on each other. Within a thread, nested `with_thread` /
`with_mutability` use the `Token` returned by `.set()` for save and
restore.

The originally-estimated approach was to thread an explicit `Thread`
parameter through every builtin (~150 sites). I rejected that in favour
of `ContextVar`s for three reasons:

- The diff is ~30 lines instead of ~600.
- `contextvars` is the canonical Python idiom for exactly this use case
  (asyncio, FastAPI, Sentry, OpenTelemetry all use it).
- The "per-evaluation state passed implicitly" semantics map cleanly:
  builtins that need the Thread call `current_thread()`; builtins that
  don't, ignore it.

The trade-off is one Pyright/typing point: `ContextVar.get(default)`
returns `T | None`, so callers handle the unset-context case. This is
fine in practice — only relevant for unit tests that build values
directly without a Thread.

###### Cost vs estimate

Estimated 1–2 days, low difficulty. Actual: about an hour, mostly
mechanical. The 8-test suite in `tests/test_thread_safety.py` covers
parallel exec_file, parallel `sorted(key=fn)` callbacks, parallel
`freeze()`, parallel reporter, nested exec_file in one thread, and
stress sweeps at 2/4/8 workers.

##### Phase B — step counter

###### What was done

Added `Thread.steps`, `Thread.max_steps`, `Thread.on_max_steps`. New
`tick()` method increments and raises `StepLimitExceeded` when the cap
is exceeded; an optional callback fires once before the raise (modeled
on starlark-go's `Thread.OnMaxSteps`).

Charged at three sites in `eval/evaluator.py`:

- Top of `_exec_stmt` — one charge per statement.
- Top of `_eval_expr` — one charge per expression-node visit.
- Entry of `call()` — one charge per call (catches builtin→user
  callbacks like `sorted(key=fn)` that bypass `_eval_expr`).

The unit is intentionally coarse and matches starlark-java's documented
choice. It is **not commensurable** with bytecode or wall-clock time.
Sub-expressions tick recursively so `sum([i for i in range(N)])` is
bounded by O(N), not O(1).

###### Cost vs estimate

Estimated 1 day, low difficulty. Actual: a couple of hours. 11
step-counter tests cover unlimited default, exact-cap raise, the
`StepLimitExceeded < ResourceLimitExceeded < EvalError` class hierarchy,
callback firing semantics, custom-error callbacks, and the threat-model
adversarial patterns.

##### Phase C — heap counter (charge-only)

###### What was done

Added `Thread.allocs`, `Thread.max_allocs`, `Thread.on_max_allocs`. New
`add_allocs(n)` method increments and raises `AllocLimitExceeded` when
the cap is exceeded; mirrors `tick()` for the alloc dimension.

Charged at every value-allocating site (see `_charge` in
`eval/values.py` and `_charge_thread_alloc` in `eval/evaluator.py`):

- `StarlarkList.__init__`, `.append`, `.extend`.
- `Dict.__init__`, `.__setitem__` (only on new keys), `.setdefault`
  (only on new keys), `.update` (by net new entries).
- `StarlarkSet.__init__`, `.add` (only on new elements).
- `Range.__post_init__` (constant; range is lazy).
- Tuple-literal expressions and `tuple` results from `_plus` / `_multiply`.
- String allocations from `_plus` / `_multiply` (concatenation and
  repeat, the only meaningful in-Starlark string growth paths).

Sizes are approximate constants in `eval/limits.py` (`ALLOC_LIST_BASE`,
etc.), calibrated from `sys.getsizeof` on a 64-bit CPython 3.11 build
and rounded to round numbers. The counter is documented as approximate.

**Charge-only by design.** The counter measures *cumulative
allocation*, not live-memory residency. Refunding live bytes would
require `weakref.finalize` on every value; this was rejected because:

- Python's GC is non-deterministic, so the running total can briefly
  exceed the bound between allocation and finalizer.
- Cycles defeat refcount-based release.
- Native containers (str/tuple) cannot accept weakrefs.
- Multi-threading would need locks on the increment path.

The "cumulative" semantics make the bound predictable but conservative.
Hosts should size `max_allocs` at 2–4× the expected steady-state
working set.

###### Cost vs estimate

Estimated 2–3 days, medium difficulty. Actual: a few hours, easier than
expected. 19 heap-counter tests cover unlimited default, exact-cap
raise, exception class hierarchy, callback firing semantics, the
threat-model adversarial patterns (`[0] * N`, big dict, big set,
list+list in a loop, tight string concatenation, string/tuple repeat),
step- and alloc-limit independence, and rejection of negative deltas.

The estimate was conservative because every allocation site touched
goes through one of three chokepoints (`StarlarkList.__init__`,
`_plus`, `_multiply`); the change is intrusive but uniform, and the
test surface is small.

##### What's still on the table: high-water heap tracking

A future implementation could track *live* bytes via
`weakref.finalize` callbacks that decrement `Thread.allocs` when a
value is GC'd. This would change the bound from "cumulative
allocation" to "high-water mark of live memory", which is what most
hosts intuitively expect.

###### Estimate

Difficulty: high. Time: 5–7 days, plus careful testing of GC behaviour
under load.

###### Cost the estimate didn't capture

- **Per-PR maintenance tax.** Every new wrapper type, every new method
  that allocates, has to think about: do I need a finalizer? Will it
  see the right Thread (the one that allocated, or the one current
  when GC fires)? Does it work under cycles? Charge-only has none of
  these — it's "increment a counter at one chokepoint."
- **Dependency on Python GC timing.** Under load you can see brief
  over-the-limit excursions between allocation and finalizer
  invocation. Workable for the threat model "can't OOM the host" but
  not for "exact bound enforced," and that's an important caveat to
  document.
- **Native containers (str/tuple) can't accept weakrefs.** You'd need
  a wrapper layer or a parallel registry keyed by `id()`.
- **Cycles defeat refcounting.** Python's cycle collector runs only
  periodically, so circular references in user code (e.g.
  `x = []; x.append(x)`) defeat finalize-based release until the GC
  sweeps.
- **Multi-threading.** Decrementing a shared counter from finalize
  callbacks needs a lock. Charge-only sidesteps this — one writer per
  Thread.

###### Recommendation

Keep the implemented charge-only model unless real users hit a case
where its cumulative semantics force them to set `max_allocs` higher
than they'd like. If they do, the high-water work is well-scoped: add
a registry of live values keyed by `id(value)`, register a `finalize`
in each constructor, decrement in the finalize callback. Document the
"transient over-limit excursions" caveat prominently.

##### Combined estimate vs actual

Originally estimated: **4.5–6.5 days** for thread-safety + step counter
+ charge-only heap counter + docs.

Actual: well under a day, dominated by writing tests rather than
wiring code. The estimate was reasonable for an explicit-`Thread`
threading approach; the `ContextVar` rewrite cut the thread-safety
phase by an order of magnitude, which made the rest cheaper too.

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

## Retrospective

End-of-project notes from the agent (Claude) doing the port, intended as
input for a write-up. First-person throughout; what follows is meant to
be honest rather than diplomatic.

### What worked

#### Phases plus the conformance dashboard

The 14-phase plan you wrote up front and `tests/test_conformance.py` as a
progress dial were the engine of this port. The phase plan gave me a
dependency graph to walk; the conformance suite gave me a number that had
to monotonically improve. I never had to hold the whole port in my head —
each phase had a small Java surface to read and a clear test delta.

Two specific properties of this combination mattered:

1. **Each phase had a falsifiable "done" criterion.** "Tests pass and one
   or more conformance files flip from xfail to xpass." Without that
   external signal I'd have spent days inside `evaluator.py` polishing
   comprehensions instead of moving to builtins.
2. **The dashboard was visible without ceremony.** `pytest -q` printed
   the count. I could see whether a refactor was a wash or a win in
   under two seconds. Cheap feedback loops are everything for this style
   of work.

I'd absolutely use the same template again. If anything I'd lean harder
on it: the phase plan you gave me let me pause whenever I felt fuzzy,
re-read the relevant `reference/` Java file end to end, and then come
back to the Python with a much clearer picture. That habit was easier to
form because the phase plan made it cheap to context-switch.

#### Python natives where they fit

Using `int`, `str`, `tuple`, `bool`, `None` directly — instead of wrapping
every Starlark value in a class — saved maybe a thousand lines of plumbing.
Equality, hashing, `repr`, and arithmetic Just Work. The lexer can emit
plain `int` and `float` for literals; the parser doesn't need to wrap
them; the evaluator doesn't need a single `unbox` call.

The price is three documented divergences:

1. Arbitrary-precision int (no overflow, no signed-32-bit checks).
2. Code-point string indexing (the Java reference indexes by UTF-16
   code unit, which surfaces in surrogate handling).
3. The bool-vs-int identity quirk: `equal()` has to override to return
   False for `True == 1`.

All three are intentional and documented under "Compatibility" in
`docs/README.md`. They're the cause of every remaining xfail.

I'm convinced this trade was right, but it's worth flagging that it
*does* cost you exact behavioral equivalence with the Java reference on
specific edge cases. If matching Bazel byte-for-byte were the goal you'd
want a `StarlarkInt` wrapper and code-unit string indexing. We got
89% conformance without either, which is a defensible point in the
design space.

#### `Mutability` as a token

The cleanest part of the port. One `Mutability` per `Module`, every
mutable value holds a reference, every mutating method calls
`self.mutability.check()`, and `Module.freeze()` flips one boolean. The
Java reference's design ported straight across; I wrote almost no
original code here.

Two small wrinkles surfaced late: `freeze(value)` (with an argument)
should freeze just *that* value, not the whole module — solved by
giving the value its own fresh frozen Mutability rather than calling
`.freeze()` on the shared one. And `freeze()` (no argument) freezes the
current module, which only works because of the `_CURRENT_MUTABILITY`
stack I'm grumpy about elsewhere.

#### Cross-validation against starlark-go

Cheap and high-signal. The `print()`-to-stderr behavior wasn't in any
unit test I'd written; the cross-validator surfaced it within ten minutes
of being wired up. Same for `-globalreassign` mode (top-level `if`/`for`)
and the BUILD-vs-`.bzl` distinction.

I should have set this up in Phase 1, not Phase 14. The reference binary
is on PATH and answers any "does it actually behave this way?" question
in five seconds; I instead read the Java source for those questions for
the first three quarters of the port. The phase plan called this out as
"when the binary is on PATH" but I treated that as optional rather than
something to make true on day one. Lesson learned.

#### `xfail` as a progress mechanism

`tests/test_conformance.py` has a dict of `XFAIL_FILES`. With
`XFAIL_STRICT = False` during the spec push, an xpass shows up as a hint
to remove the file from the list. With `XFAIL_STRICT = True` after the
list is curated, an unintended xpass becomes a CI failure. Switching
between modes — strict during development of new fixes, then strict at
the end — is a remarkably tight feedback loop for "did my change unlock
a file?". Pytest's machinery is doing all the work; the project just
uses it.

### What was annoying

#### Error-message wording is half the conformance suite's surface

A meaningful chunk of conformance failures aren't testing semantics —
they're testing the exact strings the Java reference happens to emit.
The convention in `conformance/*.star` is that an `### regex` comment on
a line declares the expected error pattern, so wording is part of the
test contract.

This means a "real" semantic gap and a wording mismatch look identical
in the failure output. They're worth different effort: the first is a
bug, the second is mechanical drudgery. Mixing them in the same pass
made me slower at both.

The xfail review you asked for was the right intervention. Forcing me
to triage every failure as **SPEC** / **WORDING** /
**JAVA-32BIT** / **JAVA-UTF16** / **TEST-DRIVER** before fixing meant I
could land the spec fixes confidently and then decide separately
whether to align the wording. Without that step I'd have gone fast and
shallow.

If I were starting over: I'd defer wording alignment until each chunk
file's *semantics* passes, then do a single sweep at the end where
matching strings is the only goal. Treating it as a separate pass also
makes it more skippable — if you don't care about byte-equivalence, you
just stop.

#### Two format-string implementations

`%`-formatting lives in `evaluator._str_format` (called from the `%`
binary operator). `.format()` lives in `string_methods._format_impl`.
They ended up as parallel parsers that reject different things and have
slightly different views of what counts as a "field name". They should
share a tokenizer.

I didn't refactor because the tests passed and I was nervous about
regressions late in the port. It's a smell. If you ever want to touch
either, do them together.

#### The `_CURRENT_THREAD` / `_CURRENT_MUTABILITY` context-var stacks

These exist so builtins like `sorted(key=fn)` can call back into the
evaluator without threading a `Thread` through every builtin's
signature. They're module-level lists with `with`-block context managers
pushing and popping.

The alternative I considered was making every builtin take an explicit
`thread` argument. That's mechanical (a few hundred lines of
boilerplate) but explicit and testable. I picked the global stack
because it was small, but the right choice was probably the explicit
threading. Globals make it harder to reason about reentrancy if the
project ever grows multi-threaded callers, and they make builtin
signatures lie about their dependencies.

If I were doing this again I'd pay the boilerplate tax up front.

#### NaN as a dict key

The spec wants `d[float("nan")] = v` to update an existing nan entry,
because all NaN values "compare equal" as dict keys. Python's
`nan != nan` makes the dict lookup miss; two `float("nan")` instances
are also not `is`-identical, so Python's identity-shortcut doesn't help
either.

I solved it by canonicalizing every nan key to a singleton at the
boundary of `Dict`. Works. But `Dict.__setitem__` and friends growing
a `_normalize_key` helper for one float quirk is a tell that the Python
data model is fighting us here, and the same pattern would need to be
duplicated for any future similar collision (e.g., negative zero, if it
ever mattered).

I don't have a clean solution. The honest answer is: this is one of the
places where the "use Python natives" decision shows its seams.

#### Stack frame growth in deep code paths

Recursive descent in the parser, recursive evaluation, recursive
JSON encoding/decoding — all of it lives on Python's stack with the
default 1000-frame limit. I added explicit depth caps in JSON to defuse
adversarial input. The parser and evaluator don't have caps, so a
sufficiently deep program will blow the stack rather than report an
"input too deeply nested" EvalError. Probably fine in practice — both
references have the same problem — but worth flagging as a known sharp
edge.

### What I'd do differently next time

- **Run the reference implementation as a CLI from day one.** Most
  behavioral questions ("does string iterate?", "does `float()` reject
  NaN?", "what does `print()` output to?") are five-second shell
  commands. I read the Java source for them and got some wrong.
- **Defer wording alignment until each chunk file's semantics pass.**
  Then do a separate sweep where matching strings is the only goal.
  Don't mix the two.
- **Don't write 900-line files.** `evaluator.py` got too big to
  navigate. Split expression eval, statement eval, arithmetic helpers,
  and call dispatch into separate modules. Same probably applies to
  `parser.py`. The cost of extra files is much lower than the cost of
  scrolling.
- **Type-check from Phase 1, not Phase 14.** Pyright caught real issues
  in test code that had been there for weeks. The version pin you
  suggested is the right move — type checkers update constantly and
  unpinned upgrades produce diffs that have nothing to do with your
  code.
- **Single journal file from the start.** `ROADMAP.md` and `STATUS.md`
  drifted from each other and the merge was overdue. One file is one
  source of truth.
- **Wire cross-validation in Phase 1.** Even with a smaller program
  set, having "does the reference agree?" available as a quick check
  during development would have caught the print-stream divergence
  weeks earlier.
- **Pick the file split before writing.** The natural shape of an
  evaluator is statement evaluation, expression evaluation, value-level
  helpers (arithmetic, comparison, indexing), and call dispatch. I wrote
  them as one file because Phase 5+6 was a single push; that's a
  reasonable cadence but the resulting file is too big.

### On the project shape

One subjective observation, since you said you were writing a post:

A port like this is unusually well-suited to LLM-driven development.
The reference is in version control, the test suite is unambiguous, the
spec is short, and "did it work" is a function call. The space of
correct designs is mostly already explored — you're translating, not
inventing — and verification is automated.

This is a different kind of task from greenfield design, where every
decision is reversible at high cost and the agent has to *judge*
whether something is right rather than *check* it. The way I'd put it:
in greenfield work the bottleneck is taste, in porting work the
bottleneck is reading speed and translation accuracy, both of which
LLMs are pretty good at.

If I were picking projects to throw at agents, I'd look for these
properties:

- **Reference implementation in source control.** Even imperfect ones
  beat prose specs.
- **Conformance suite or comparable test corpus.** A high-volume way to
  ask "did I break it?" without having to design tests yourself.
- **Short spec.** Long specs invite over-implementation; short ones
  force the agent to use the reference for ambiguous cases, which is
  what you want.
- **Phased decomposition into observable milestones.** Lexer →
  parser → evaluator is the canonical example. Each phase ends with a
  test you can run. Without that, agents (and humans) wander.
- **Permission for documented divergence.** "Match exactly" is
  open-ended; "match exactly except for these three settled
  divergences" gives an agent something to bounce off when the
  reference's choices are awkward in the target language. The
  Architectural Decisions section of `CLAUDE.md` was load-bearing here.

The combination of those properties is rare in real projects but very
common in language ports. That's probably why the LLM-port-of-X genre
keeps showing up; it's a sweet spot.

The other thing I'd note for the post: the agent rhythm that worked
well was "land a phase, run tests, commit with a message that reads
like a tutorial paragraph, push, repeat." Not because the commits were
the deliverable, but because writing the commit message forced me to
articulate what changed and why, which was a useful discipline. A
hundred-commit history where each message describes one self-contained
idea is much easier to review than a five-commit "phases 1-7" mass.

### A note to whoever resumes this

There's still work to do, even with the spec push landed:

- The format-string consolidation mentioned above.
- The `_CURRENT_THREAD` removal in favor of explicit threading.
- Splitting `evaluator.py` into 3-4 files.
- Possibly: a real `assert.star` module so we can run starlark-go's
  testdata too, not just Bazel's `ScriptTest`-style files.
- The four xfail conformance files are *not* worth the work — they
  require giving up the "Python natives" decision and we shouldn't.
  Keep them as documented divergences.

The conformance dashboard is at 34/38 with cross-validation 23/23
green. Nothing in the codebase should require deep reading to pick up
again; `docs/README.md` is the entry point.
