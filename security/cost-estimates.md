# Cost estimates: thread-safety and resource limits

These are estimates for the two largest items left on the table after
the small fixes (sandbox-boundary test, centralized size cap, depth
caps) landed. Each estimate covers difficulty, time, and added
complexity. Numbers are calibrated against the small-fixes work, which
took roughly half a day total.

## Going thread-safe

### What it means

Replace the module-level stacks `_CURRENT_THREAD` and
`_CURRENT_MUTABILITY` (in `eval/builtins.py`) and `_REPORTERS` (in
`eval/test_driver.py`) with explicit threading. After the change, two
host threads can call `starlark.eval` concurrently against different
modules without interfering with each other.

### Approach

The cleanest design is the one the retrospective already proposes:

- `BuiltinFunction.impl` becomes `Callable[[Thread, ...], Any]` rather
  than `Callable[..., Any]`. The first parameter is always the current
  `Thread`.
- `evaluator.call(fn, args, kwargs, thread)` invokes `fn.impl(thread,
  *args, **kwargs)` for builtins.
- The reporter argument used by `assert_eq` / `assert_fails` lives on
  `Thread` rather than in a module-level list.
- `Mutability` access goes through `thread.module.mutability` instead
  of the global stack.

Builtins that don't actually need the thread can ignore it. The
trade-off is verbosity: every signature gains a parameter.

### Difficulty

**Low.** The change is mechanical. Each builtin needs:

- One extra parameter in its signature.
- A `thread.module.mutability` instead of `_mut()` for any allocation
  it does.
- A `thread.<...>` instead of `_CURRENT_THREAD[-1]` for any callback
  to user-defined Starlark code.

Tests cost: low. The end-to-end tests already go through
`starlark.eval` / `exec_file`, which already have a `Thread`. The unit
tests in `tests/test_methods.py` etc. mostly call methods through
Starlark expressions, so they benefit transparently. A handful of
direct-call unit tests in `tests/test_values.py` need a `Thread`
threaded through.

### Time

**1–2 days.** Roughly:

- 2 hours: redesign `BuiltinFunction` interface and `evaluator.call`.
- 4 hours: update every builtin signature
  (~30 in `builtins.py`, ~7 in `test_driver.py`, ~30 string methods,
  ~20 collection methods, 4 json methods).
- 2 hours: update tests that construct builtins or call `_mut()` /
  `_CURRENT_THREAD` directly.
- 2 hours: shake out residual bugs from missed sites.

### Added complexity

**Slight increase**. ~150 call sites get one extra parameter; this is
boilerplate, not conceptual complexity. In return, the code becomes
substantially easier to reason about: there's no implicit per-eval
state. Pyright also gets more useful (the global stacks today are
typed `list[Any]`, which forces casts at call sites).

### Recommendation

Worth doing. It's the single largest cleanup left and unblocks any
future feature that needs to read or write per-thread state (resource
counters, profiling, host-supplied print sinks, …).

## Implementing resource limits

The host-facing API would be:

```python
starlark.exec_file(
    src,
    max_steps=10_000_000,        # CPU bound
    max_alloc_bytes=64 * 1024**2,  # 64 MB memory bound
)
```

A `Thread` with neither set behaves as today; with one or both set, the
interpreter aborts with `EvalError` when the limit is exceeded. Both
features depend on the thread-safety work above (the counters belong
on the `Thread`).

### Step counter

#### What it means

Increment a counter on every statement executed and every loop
iteration. When it reaches `max_steps`, raise an uncatchable
`EvalError`. This bounds CPU time as a function of source steps,
independent of how much work each step does.

#### Approach

- One `int` field on `Thread`: `Thread.steps`.
- Increment at three sites in `eval/evaluator.py`:
  - Top of `_exec_stmt` (one charge per statement).
  - Inside the for-loop body in `_exec_stmt` (one charge per
    iteration).
  - Top of `_eval_expr` (debatable — without this, a single huge
    expression like `sum([x for x in range(N)])` is one step). I'd do
    it; the cost is negligible and it makes the bound predictable.
- Charge inside `call()` for each user-function invocation.
- `Thread.tick()` raises if `self.steps >= self.max_steps`.

This is *not* a perfect CPU bound — a single builtin like
`sorted(huge)` does O(N log N) work for one charge. But it bounds the
*number of Starlark-level operations*, which is what the spec implies
when it says "execution is finite".

#### Difficulty

**Low.** Maybe 50 lines.

#### Time

**1 day** including tests.

#### Added complexity

**Negligible.** It's a counter on `Thread`, three increment sites, and
one check.

### Heap counter

#### What it means

Charge approximate bytes on every value allocation. When the running
total exceeds `max_alloc_bytes`, raise `EvalError`. Bounds memory
*high-water mark* (or *cumulative allocation*, depending on the
implementation choice).

#### Approach: charge-only (simpler)

- One `int` field on `Thread` or `Module`: `bytes_allocated`.
- Charge at allocation sites:
  - `StarlarkList.__init__` charges `~80 + 8 * len(items)`.
  - `Dict.__init__` charges `~240 + 64 * len(items)`.
  - `StarlarkSet.__init__` similar.
  - `_plus` for str/list/tuple charges the new size.
  - `_multiply` similarly.
  - `json.decode` charges as it builds containers.
  - `range()` charges constant — Range is lazy, so the materialization
    cost is paid by `list(range(...))` etc.
- Never refund. This is simpler than tracking residency but means the
  counter measures *cumulative allocation*, not live memory. For a
  bound that says "this evaluation can allocate at most N bytes total"
  this is the right semantics.

#### Approach: high-water tracking (more accurate, harder)

Track live allocations using `weakref.finalize` on each value.
Decrement the counter when a value is GC'd. The bound becomes
"high-water mark of live memory". Caveat: Python's GC is not
deterministic, so the running total can exceed the bound briefly
between allocations and finalizers. Workable but adds non-trivial
complexity and a small per-value overhead.

#### Difficulty

**Medium.** ~150 lines for charge-only. ~400 lines for high-water
tracking, plus careful testing of the GC behavior.

#### Time

- **2–3 days** for charge-only.
- **5–7 days** for high-water tracking.

#### Added complexity

**Charge-only** is conceptually simple (a counter on the Module,
incremented at known allocation sites) but touches every value
constructor. The change is intrusive but uniform.

**High-water** introduces a non-obvious dependency on Python GC
timing; under load you can see brief over-the-limit excursions.
Workable for the threat model "can't OOM the host" but not for "exact
bound enforced" — and that's an important caveat to document.

#### Recommendation

If you want this, do **charge-only** first. It defends against the
DoS scenarios both reviewers cited (`[0] * 10**8`, deeply iterative
allocation) without the GC complexity. Reach for high-water only if
real users hit a case where charge-only's "cumulative" semantics
forces them to set `max_alloc_bytes` higher than they'd like.

## Combined estimate

Doing both, charge-only:

- Thread-safety (prerequisite): **1–2 days**.
- Step counter: **1 day**.
- Heap counter (charge-only): **2–3 days**.
- Documentation, additional tests, threat-model update: **0.5 day**.

**Total: 4.5–6.5 days.**

Doing both, high-water:

- Add 3–4 days for the GC tracking. **7–10 days total.**

If only one is wanted: the **step counter** is cheaper, smaller, and
prevents the most common adversarial pattern (infinite loops via
`for i in range(huge)`). I'd start there.

## What this would not give you

Even with both counters, the interpreter is not a security boundary
suitable for arbitrary public input without a host-side OS sandbox
(`resource.setrlimit`, separate process, …). Counters defend against
configurations that are bugs or annoyances; the OS sandbox defends
against everything else.
