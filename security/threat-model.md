# Threat model

Adapted from a sibling project's template. The intent is to make
explicit what this interpreter defends against and what it does not, so
security reviewers don't have to guess and downstream users can decide
whether this implementation matches their needs.

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
  returns**, with two known exceptions:
  - `print()` writes to `sys.stderr`. The host can redirect stderr
    before evaluating if it wants log isolation.
  - The interpreter uses module-level stacks
    (`_CURRENT_THREAD`, `_CURRENT_MUTABILITY` in `eval/builtins.py`,
    `_REPORTERS` in `eval/test_driver.py`) to thread context into
    builtins. These are pushed and popped around each `eval` /
    `exec_file` call, but they are *not safe under concurrent use*
    of the interpreter from multiple host threads. See "Limitations"
    below.

## What the interpreter does **not** defend against

- **CPU exhaustion.** There is **no step counter**. A `for` loop over
  a large `range`, a deeply nested non-recursive computation, or any
  CPU-bound construction can run until the host process is killed or
  the Python recursion limit is hit. The host is responsible for
  enforcing wall-clock or CPU-time bounds (e.g. via
  `signal.alarm`, `resource.setrlimit`, or running the evaluator
  in a subprocess).
- **Memory exhaustion (in the small).** There is **no heap
  counter**. Many small allocations can incrementally consume
  unbounded memory. We only defend against single-allocation worst
  cases via soft caps (see "Defences against the worst single
  allocation" below).
- **Concurrent reentrancy.** The module-level context stacks listed
  above are not safe if a host runs two evaluations in parallel in
  the same Python process. Single-threaded use is fine; multi-threaded
  hosts must serialise calls.

## Defences against the worst single allocation

The interpreter has soft caps that prevent the most common adversarial
inputs from OOM-ing or hanging the host even without full resource
counters:

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
~10M elements; a configuration that does this in a tight loop ten
million times will eventually OOM.

## Stricter modes the host may want

If the host needs the stricter "bounded CPU and memory" guarantee that
both security reviewers assumed, two complementary mechanisms are
appropriate (cost estimates in `security/cost-estimates.md`):

1. **A step counter on the `Thread`**, charged on every statement and
   loop iteration, configurable via a `max_steps` parameter.
2. **A heap counter on the `Module`**, charged on every allocation,
   configurable via a `max_alloc_bytes` parameter.

Both would be **opt-in features**, not always-on, so configuration code
that's known to be fast and small doesn't pay the per-instruction
overhead.

## Reviewer-recommended host-side defence

In addition to interpreter-level bounds, hosts that accept untrusted
configurations from arbitrary sources (e.g. a public web service)
should run evaluation in a separate OS process with `resource.setrlimit`
applied. This gives a hard guarantee independent of any interpreter
bug. The interpreter's in-process bounds defend against accident; OS
limits defend against the unknown.
