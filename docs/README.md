# starlark-python — developer docs

Brief tour of the codebase and the public API. The top-level
[`README.md`](../README.md) is for users; this is for people working on the
interpreter itself.

The Starlark language spec lives next to this file as
[`spec.md`](spec.md).

## Compatibility with the reference implementations

These are the user-visible places this implementation diverges from the
Bazel Java reference and from `starlark-go`. Everything else aims for
exact behavioral and string-output equivalence.

- **Integers are Python `int`.** Arbitrary precision; no overflow. The
  Java reference uses a `StarlarkInt` union of int32 / int64 /
  BigInteger and surfaces overflow at the boundary.
- **Strings are indexed by Unicode code point.** The Java reference
  indexes by UTF-16 code unit, which produces surprising results on
  non-BMP characters (a single emoji is one index in our world, two
  indices in Java's). The spec leaves this implementation-defined.
- **No 32-bit-range checks for `range()` / `*` repeat / etc.** Native
  `int` arithmetic doesn't overflow, so these checks would be
  artificial. We instead cap container allocations at 16M elements with
  a less specific error message.
- **`if` and `for` are allowed at top level.** This matches `starlark-go`
  in `-globalreassign` mode and the `.bzl` file dialect; it diverges
  from BUILD-file mode, which forbids them. We don't currently
  distinguish dialects — the host is expected to apply a stricter
  pre-check if it cares (Bazel does this via `FileOptions`).
- **`while` and recursion are forbidden.** Same as both references in
  their default mode.
- **`load()` is host-mediated.** The host supplies a `Loader` callable
  (`Callable[[str], Module]`); without one, `load()` raises. There is no
  filesystem access by default.
- **`print()` writes to stderr** and ends with a newline. This matches
  both references; cross-validation in `tests/test_cross_validation.py`
  asserts byte-equal stderr+stdout output.

## Codebase structure

    src/starlark/
      __init__.py             Public API: eval, exec_file, EvalError, Module, Thread.
      cmd.py                  Argparse CLI ('starlark-python' console script & 'python -m starlark').
      __main__.py             Trampoline so 'python -m starlark' works.
      syntax/                 Source -> AST. Mirrors net.starlark.java.syntax.
        tokens.py             TokenKind enum + Token dataclass.
        location.py           FileLocations: offset -> (line, column) lookup.
        errors.py             SyntaxError record + StarlarkSyntaxException.
        lexer.py              Stream-style scanner with INDENT/OUTDENT.
        ast.py                Dataclass nodes for every grammar construct.
        parser.py             Recursive-descent parser; produces a StarlarkFile.
        resolver.py           Classifies each Identifier (LOCAL/FREE/GLOBAL/...);
                              computes per-function locals + freevars; structural
                              checks (break outside loop, etc.).
      eval/                   Runtime. Mirrors net.starlark.java.eval.
        errors.py             EvalError + CallFrame.
        mutability.py         The per-Module Mutability token.
        module.py             Module: globals dict + Mutability.
        values.py             Native types (None/bool/int/float/str/tuple) +
                              wrappers (StarlarkList, Dict, StarlarkSet, Range,
                              BuiltinFunction). Helpers: starlark_type, truth,
                              equal, less_than, repr_starlark, str_starlark,
                              check_hashable.
        function.py           StarlarkFunction (def / lambda) + bind_arguments.
        evaluator.py          Tree-walking interpreter. Frame, Thread, eval_file,
                              call.
        methods.py            Per-type method-table dispatch (string / list /
                              dict / set).
        string_methods.py     All string methods.
        collection_methods.py All list / dict / set methods.
        builtins.py           Universal builtins (len, range, sorted, sum, ...).
        json_module.py        json.encode / decode / encode_indent / indent.
        test_driver.py        Bazel ScriptTest-style predeclared helpers
                              (assert_eq, assert_, assert_fails, freeze, struct).
        loader.py             Loader protocol + FileLoader for load() statements.

    tests/                    Pytest suite, ~400 tests.
      test_lexer.py / test_parser.py / test_resolver.py / test_values.py /
      test_eval.py / test_methods.py / test_builtins.py / test_load.py /
      test_json.py
      test_lexer_conformance.py / test_parser_conformance.py /
      test_resolver_conformance.py
      test_conformance.py     Parameterized over conformance/*.star, splits
                              chunks on '\\n---\\n', honors '### regex' error
                              markers exactly as Bazel ScriptTest.java does.
      test_cross_validation.py Optional cross-check against starlark-go's
                              binary; skipped cleanly when not on PATH.

    conformance/              38 .star files copied verbatim from Bazel.

## Public API

Everything lives at the package root. The whole surface is:

```python
import starlark
```

### `starlark.eval(source: str, filename: str = "<expr>", **env) -> Any`

Parse, resolve, and evaluate `source` as a single expression. Returns
the value. `**env` is added to the universal namespace on top of the
built-in set (`len`, `range`, `print`, `json`, …).

```python
starlark.eval("1 + 2")                   # 3
starlark.eval("len('hello')")            # 5
starlark.eval("json.encode([1, 2])")     # '[1,2]'
```

### `starlark.exec_file(source, filename="<file>", *, predeclared=None, universal=None, loader=None, max_steps=None, on_max_steps=None, max_allocs=None, on_max_allocs=None) -> Module`

Parse, resolve, and execute `source` as a Starlark file. Returns the
populated `Module`. `predeclared` adds host-supplied names visible to
this file only; `universal` adds names to the read-only universe;
`loader` resolves `load()` statements. The `max_*` / `on_max_*` kwargs
configure the opt-in resource limits — see "Resource limits" below.

```python
m = starlark.exec_file('''
def fact(n):
    result = 1
    for i in range(1, n + 1):
        result *= i
    return result

z = fact(5)
''')
m.globals["z"]   # 120
m.freeze()       # all values created in this module are now read-only
```

### `starlark.Module`

A container of module-global bindings (`module.globals: dict[str, Any]`) plus
the `Mutability` token (`module.mutability`) shared by every mutable value
created during execution. `module.freeze()` is O(1) and locks every owned
value.

### `starlark.Thread`

The runtime state for a single evaluation: the executing module, the
predeclared/universal envs, the call stack, and an optional `loader`.
Most users construct one indirectly via `exec_file`/`eval`.

### `starlark.EvalError`

Raised for any runtime semantic error (type mismatch, division by zero,
frozen mutation, undefined name, etc.). Carries `message: str` and
`frames: list[CallFrame]` for traceback rendering.

### `starlark.ResourceLimitExceeded` / `StepLimitExceeded` / `AllocLimitExceeded`

`StepLimitExceeded` and `AllocLimitExceeded` both subclass
`ResourceLimitExceeded`, which subclasses `EvalError`. Existing
`except EvalError` handlers catch them; hosts that want to distinguish
"DoS-style abort" from a normal Starlark error catch
`ResourceLimitExceeded`. See "Resource limits" below.

## Resource limits

Off by default. Hosts that accept untrusted Starlark configure them
via `exec_file` / `eval` kwargs:

```python
m = starlark.exec_file(
    src,
    max_steps=10_000_000,                # CPU bound (Starlark operations)
    max_allocs=64 * 1024 * 1024,         # memory bound, approximate
    on_max_steps=lambda t: log(f"step cap at {t.steps}"),
    on_max_allocs=lambda t: log(f"alloc cap at {t.allocs} bytes"),
)
print(m.thread.steps, m.thread.allocs)   # readable after a successful run
```

### Step counter

`Thread.steps` is a monotonic counter; `Thread.max_steps` is the cap
(`None` = unlimited). On excess, raises `StepLimitExceeded`. Charged at
three sites: top of every statement (`_exec_stmt`), top of every
expression node (`_eval_expr`), and entry of every call (`call()`).

The unit is intentionally coarse — Starlark operations, not Python
instructions or bytecode — and matches starlark-java's documented
choice. Sub-expressions tick recursively, so
`sum([i for i in range(N)])` is bounded by O(N), not O(1).

It is *not* a hard CPU bound: a single big builtin like
`sorted(huge_list)` does O(N log N) Python-level work for one step
charge. Combine with `resource.setrlimit` or a subprocess for a hard
ceiling.

### Heap counter (charge-only)

`Thread.allocs` is a monotonic byte counter; `Thread.max_allocs` is
the cap (`None` = unlimited). On excess, raises `AllocLimitExceeded`.
Charged in every container constructor, every mutating
`append`/`extend`/`update`/`add`, and every `+`/`*` that produces a
new container or string. Sizes are approximate constants in
`eval/limits.py`.

The counter is **charge-only**: values that go out of scope are not
refunded. The bound it expresses is *cumulative allocation*, not
*live memory*. A program that allocates 64 MB in scratch values and
lets the GC reclaim them will still report 64 MB used. Size
`max_allocs` at 2–4× the expected steady-state working set.

### `on_max_*` callback semantics

Each `on_max_*` callback is invoked **once**, before the
corresponding `*LimitExceeded` is raised. The callback can:

- Return normally (the default raise still fires).
- Raise its own exception (pre-empts the default raise; the host
  sees the custom exception).
- Mutate the `Thread` (e.g. log, increment a host metric).

Subsequent overruns within the same evaluation do not re-fire the
callback — it's a one-shot.

### Threat model

[`security/threat-model.md`](../security/threat-model.md) documents
the full sandbox boundary: what the interpreter defends against (no
filesystem / network / subprocess / Python introspection, concurrent
use is safe), what the opt-in counters do and don't promise, and the
recommended host-side belt-and-braces (run in a subprocess with
`resource.setrlimit`).

## Loader protocol

`Loader` is just `Callable[[str], Module]`. Pass it as `loader=` to
`exec_file` (or set `Thread.loader` directly).

```python
from starlark.eval.loader import FileLoader

loader = FileLoader(exec_file=starlark.exec_file, search_paths=[".", "lib"])
starlark.exec_file(open("main.star").read(), loader=loader)
```

`FileLoader` caches modules by path and freezes them on first load.

## Test-driver helpers

The Bazel conformance suite uses predeclared functions: `assert_eq`,
`assert_`, `assert_fails`, `freeze`, `struct`, `mutablestruct`,
`int_mul_slow`. They live in `eval/test_driver.py` and aren't installed
unless the host explicitly passes them via `predeclared=`.

```python
from starlark.eval.test_driver import make_predeclared, with_reporter

with with_reporter() as reporter:
    starlark.exec_file("assert_eq(1, 2)", predeclared=make_predeclared())
    print(reporter.errors)   # ['assert_eq: 1 != 2']
```

`push_reporter` / `pop_reporter` exist for backwards compatibility but
`with_reporter` is the preferred form — both are thread-safe under
nesting.

## Adding a builtin

For a *universal* builtin available to every Starlark file:

```python
# src/starlark/eval/builtins.py
def b_double(x):
    if not isinstance(x, int) or isinstance(x, bool):
        raise EvalError(f"double() requires int, got {starlark_type(x)}")
    return x * 2

# In make_universal():
("double", b_double),
```

For a *method* on an existing type (string, list, dict, set):

```python
# src/starlark/eval/string_methods.py (or collection_methods.py)
def s_shout(self, suffix=""):
    return self.upper() + suffix

# In register_all():
("shout", s_shout),
```

For builtins that need to call back into Starlark (e.g. `key=` callbacks)
use `_call_starlark(fn, *args)` from `eval.builtins`. It reads the
current `Thread` from the `_CURRENT_THREAD` context variable, which the
evaluator sets for the duration of every call. Concurrent evaluations
in different host threads are isolated automatically.

For builtins that allocate mutables (lists, dicts), call `_mut()` to get
the current Module's Mutability:

```python
from .builtins import _mut
return StarlarkList(items, _mut())
```

## Adding an AST node

1. Add a `@dataclass(slots=True)` subclass of `Expression` or `Statement`
   in `syntax/ast.py`.
2. Teach the parser to emit it (`syntax/parser.py`).
3. Teach the resolver to recurse through it (`syntax/resolver.py`).
4. Teach the evaluator (`eval/evaluator.py::_exec_stmt` or
   `_eval_expr`).
5. Add unit tests in `tests/test_parser.py`, `tests/test_resolver.py`,
   `tests/test_eval.py`.

## Conformance suite workflow

1. Run `poe test` — failures appear in `tests/test_conformance.py`.
2. To debug one file, drop into a Python REPL:

   ```python
   import starlark
   from starlark.eval.test_driver import make_predeclared, push_reporter, pop_reporter
   src = open("conformance/dict.star").read()
   r = push_reporter()
   try:
       for chunk in src.split("\n---\n"):
           try:
               starlark.exec_file(chunk, predeclared=make_predeclared())
           except Exception as e:
               print("EXC:", e)
       for msg in r.errors: print(msg)
   finally:
       pop_reporter()
   ```

3. Once a file passes, remove it from `XFAIL_FILES` in
   `tests/test_conformance.py`.
