# Threat model

The intent is to make explicit what this interpreter defends against
and what it does not, so security reviewers don't have to guess and
downstream users can decide whether this implementation matches their
needs.

## What the interpreter defends against

Source files (`.star` programs and the values they construct) are
**untrusted**. A program may produce malicious *values* — any
configuration language permits that, since even static JSON can
declare a billion-element array and YAML has the canonical
billion-laughs entity-expansion attack. A program **cannot** perform
malicious actions:

- **No filesystem read or write.** No builtin opens, reads, writes,
  globs, or stats files. The only filesystem-touching code in the
  package is `eval/loader.py:FileLoader`, which is a host-supplied
  helper; it is **never** active unless the host explicitly
  instantiates and passes it.
- **No network access.** No builtin opens sockets, performs HTTP
  requests, or resolves hostnames.
- **No subprocess execution.** No builtin invokes `os.system`,
  `subprocess.*`, or any other process-creating call.
- **No introspection that reveals or reaches Python objects outside
  the sandbox.** Attribute access on Starlark values is routed through
  per-type method tables (`eval/methods.py`) and the `fields` dict on
  struct-like values; the interpreter never calls Python's `getattr`
  on a user-controlled object. As a result the classic Python
  sandbox-escape chain
  `().__class__.__bases__[0].__subclasses__()` is unreachable —
  `__class__` is not a recognised attribute name on any
  Starlark-visible value, and the wrapper types
  (`StarlarkList`, `Dict`, `StarlarkSet`, `Range`) do not subclass
  their Python equivalents. `tests/test_sandbox_boundary.py` enforces
  the latter and that no builtin ever returns a raw Python `list` /
  `dict` / `set`.
- **No persistent mutation of host process state visible after eval
  returns**, with one known exception:
  - `print()` writes to `sys.stderr`. The host can redirect stderr
    before evaluating if it wants log isolation.
- **Concurrent use is safe.** The three pieces of per-evaluation
  context (current `Thread`, current `Mutability`, the test-driver
  `Reporter`) live in `contextvars.ContextVar`s. Each OS thread sees
  its own context, so two host threads can call `starlark.exec_file`
  in parallel without stomping on each other.
  `tests/test_thread_safety.py` enforces this with parallel-eval,
  parallel-`sorted(key=fn)`, parallel-`freeze()`, parallel-reporter,
  and stress sweeps at 2/4/8 workers.

## Bounded-resource modes the host may opt into

Bounded-CPU and bounded-memory evaluation are **opt-in features**, off
by default. A configuration that's known to be fast and small doesn't
pay the per-instruction counter overhead. Hosts that accept untrusted
input set both via `exec_file` kwargs (or directly on `Thread`):

```python
import starlark

mod = starlark.exec_file(
    src,
    max_steps=10_000_000,                  # CPU bound
    max_allocs=64 * 1024 * 1024,           # 64 MB memory bound
    on_max_steps=lambda t: log("step limit reached"),  # optional callback
    on_max_allocs=lambda t: log("alloc limit reached"),
)

# After a successful run hosts can read the cost:
print(f"used {mod.thread.steps} steps, {mod.thread.allocs} bytes")
```

Both errors subclass `EvalError`, so existing `except EvalError`
handlers see them. A finer-grained `except` is also possible:
`StepLimitExceeded` and `AllocLimitExceeded` both subclass
`ResourceLimitExceeded`.

### Step counter

`Thread.steps` is monotonic; `Thread.max_steps` is the cap. Charged at
three sites: top of every statement (`_exec_stmt`), top of every
expression node (`_eval_expr`), and entry of every `call()`. The unit
is intentionally coarse — Starlark operations, not Python instructions
— and matches starlark-java's documented choice. Sub-expressions tick
recursively, so `sum([i for i in range(N)])` is bounded by O(N), not
O(1).

The unit is **not commensurable** with bytecode or wall-clock time. A
single `sorted(huge_list)` or `dict.update(huge_dict)` does O(N log N)
or O(N) work for one Starlark step, so a step bound is a soft CPU
bound, not a hard one. Combine with `resource.setrlimit` for a hard
CPU ceiling against unknown-unknowns.

### Heap counter

`Thread.allocs` is monotonic; `Thread.max_allocs` is the cap.
Charge-only — values that go out of scope are **not refunded**. The
counter measures *cumulative allocation*, not live-memory residency.
Charged in every container constructor (`StarlarkList`, `Dict`,
`StarlarkSet`, `Range`), every mutating concat / extend / insert, and
every `+` / `*` that produces a new container or string. Sizes are
approximate (rounded constants in `eval/limits.py`); precise residency
would need `weakref` GC tracking, which the cost-estimates document
rejected as too complex for the security benefit.

The cumulative-vs-live semantics matter: a program that allocates 64
MB in scratch values and lets them GC'd will still report 64 MB used.
Hosts should choose `max_allocs` accordingly — `2x` to `4x` the
expected steady-state working set is a reasonable starting point.

## What the interpreter still does **not** defend against

Even with both counters enabled:

- **Wall-clock time outside the step counter.** A single big builtin
  call (e.g. `sorted(N=10⁶ items)`) does O(N log N) Python-level work
  for one step charge.
- **Heap residency vs cumulative allocation.** `max_allocs` bounds the
  *sum* of bytes ever requested from the counter, not the *live*
  bytes. A loop that allocates and discards N MB per iteration will
  exhaust an `max_allocs=N` budget after one iteration even though
  Python's GC keeps memory bounded.
- **Adversarial input outside Starlark's control.** A configuration
  that calls a host-supplied builtin in a loop, where that builtin
  blocks on I/O or holds a lock, is the host's problem to bound.

## Always-on defences against the worst single allocation

Independent of opt-in counters, the interpreter has soft caps that
prevent the most common adversarial inputs from OOM-ing or hanging the
host even when no `max_*` is set:

- **`MAX_CONTAINER_ELEMENTS = 16M`** (`eval/limits.py`). Applied to
  every materializing operation: `list(iter)`, `tuple(iter)`,
  `set(iter)`, `sorted(iter)`, `reversed(iter)`, `enumerate(iter)`,
  `zip(*iters)`, `min`/`max`/`sum` on a single iterable, the
  `+` concatenation on lists / tuples / strings, and `list.extend`.
  Inputs that would exceed this raise a clean `EvalError` with the
  Java-reference wording (`excessive capacity requested`).
- **Repeat cap.** `*` repeat on lists, tuples, and strings goes
  through the same cap with operand-aware messages
  (`excessive repeat (length * factor elements)` or
  `got X for repeat, want value in signed 32-bit range`).
- **`MAX_NESTING_DEPTH = 256`**. Both the parser and the evaluator
  track AST-walk depth and abort with a clean
  `StarlarkSyntaxException` / `EvalError` before Python's
  `RecursionError` fires. `repr_starlark` has the same cap so deeply
  nested values built at runtime
  (`for i in range(N): x = [x]`) don't blow the stack on print.
- **JSON decoder depth cap.** Same constant; documented in
  `eval/json_module.py`.
- **Recursion forbidden** (per spec). User functions cannot call
  themselves directly or indirectly; this is checked at every call
  via `Thread.active`.
- **`while` forbidden** (per spec). Rejected at parse time.
  Combined with the above, this prevents unbounded recursion through
  user-defined control flow.

These are *single-shot* defences — they bound the worst single
allocation or call chain. They do **not** bound aggregate work across
many smaller operations. A configuration that builds 100 lists of
100,000 elements each in a `for` loop will succeed and consume
~10M elements; without `max_allocs`, a tight loop doing this ten
million times will eventually OOM.

## Reviewer-recommended host-side defence

In addition to interpreter-level bounds, hosts that accept untrusted
configurations from arbitrary sources (e.g. a public web service)
should run evaluation in a separate OS process with `resource.setrlimit`
applied. This gives a hard guarantee independent of any interpreter
bug. The interpreter's in-process bounds defend against accident; OS
limits defend against the unknown.
