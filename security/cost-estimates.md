# Implementation notes: thread-safety and resource limits

These were the largest items left after the small fixes (sandbox-boundary
test, centralized size cap, depth caps) landed. This document records
what was done, what it actually cost, and what the remaining options are
if the host needs stricter bounds than the implemented charge-only model
provides.

## Phase A — thread-safety

### What was done

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

### Cost vs estimate

Estimated 1–2 days, low difficulty. Actual: about an hour, mostly
mechanical. The 8-test suite in `tests/test_thread_safety.py` covers
parallel exec_file, parallel `sorted(key=fn)` callbacks, parallel
`freeze()`, parallel reporter, nested exec_file in one thread, and
stress sweeps at 2/4/8 workers.

## Phase B — step counter

### What was done

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

### Cost vs estimate

Estimated 1 day, low difficulty. Actual: a couple of hours. 11
step-counter tests cover unlimited default, exact-cap raise, the
`StepLimitExceeded < ResourceLimitExceeded < EvalError` class hierarchy,
callback firing semantics, custom-error callbacks, and the threat-model
adversarial patterns.

## Phase C — heap counter (charge-only)

### What was done

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

### Cost vs estimate

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

## What's still on the table: high-water heap tracking

A future implementation could track *live* bytes via
`weakref.finalize` callbacks that decrement `Thread.allocs` when a
value is GC'd. This would change the bound from "cumulative
allocation" to "high-water mark of live memory", which is what most
hosts intuitively expect.

### Estimate

Difficulty: high. Time: 5–7 days, plus careful testing of GC behaviour
under load.

### Cost the estimate didn't capture

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

### Recommendation

Keep the implemented charge-only model unless real users hit a case
where its cumulative semantics force them to set `max_allocs` higher
than they'd like. If they do, the high-water work is well-scoped: add
a registry of live values keyed by `id(value)`, register a `finalize`
in each constructor, decrement in the finalize callback. Document the
"transient over-limit excursions" caveat prominently.

## Combined estimate vs actual

Originally estimated: **4.5–6.5 days** for thread-safety + step counter
+ charge-only heap counter + docs.

Actual: well under a day, dominated by writing tests rather than
wiring code. The estimate was reasonable for an explicit-`Thread`
threading approach; the `ContextVar` rewrite cut the thread-safety
phase by an order of magnitude, which made the rest cheaper too.
