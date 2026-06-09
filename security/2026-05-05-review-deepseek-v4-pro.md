# Security Review of the Starlark Implementation

> **Superseded.** This review predates the resource-limit implementation
> (step counter, heap counter, `MAX_CONTAINER_ELEMENTS`, `MAX_NESTING_DEPTH`,
> `MAX_INT_BITS`, and value-level depth bounding). Its "no step/heap counter"
> finding is stale; see [`threat-model.md`](threat-model.md) for the current
> state. Retained for historical context.

**Date:** 2026-05-04  
**Reviewer:** DeepSeek V4 Pro
**Scope:** The pure-Python Starlark interpreter in this repository, assessed against the threat model described in the project’s design discussions.

## Threat Model (Recap)

- Configurations are **untrusted**.
- A config may produce malicious *values* (e.g., huge data structures), but must not perform malicious *actions*.
- No filesystem access, no network, no subprocess execution.
- No introspection that reaches or reveals Python objects outside the sandbox.
- CPU consumption must be bounded (step counter).
- Memory consumption must be bounded (heap counter).
- Determinism is not required.

## Sandbox Boundary

The interpreter implements a **closed-world evaluator** for the Starlark language. User code never directly interacts with arbitrary Python objects. All values are either Python natives (`int`, `str`, `bool`, `None`, `tuple`) or instances of the interpreter’s own mutable wrappers (`StarlarkList`, `Dict`, `StarlarkSet`). Attribute access (`x.attr`) is routed through a per-type method table (`methods.py`) and a `fields` dictionary on struct-like values; it never calls Python’s `getattr` on a user-visible object. This design prevents the classic `().__class__.__bases__[0].__subclasses__()` escape chain because `__class__` is simply not a recognised attribute name.

**Assessment:** The sandbox boundary appears sound. There is no path from user code to a Python type object, frame, or module.

### Potential Boundary Weaknesses

1. **Built-in functions implemented in Python** (`builtins.py`, `string_methods.py`, `collection_methods.py`, `json_module.py`) receive Starlark values and return Starlark values. If a builtin inadvertently returns a raw Python object (e.g., a `list` instead of a `StarlarkList`), that object would be exposed to user code and could be introspected. A manual audit of every builtin return path is advisable; the current code appears careful, but this is the most likely place for a future regression.

2. **The `json` module** constructs `StarlarkList` and `Dict` using `_mut()` to obtain the current module’s `Mutability`. This is correct. The decoder (`_Decoder`) uses Python’s `int()` and `float()` to parse numbers; these functions are safe and cannot be abused to escape.

3. **The `print` builtin** writes to `sys.stderr`. This is intentional (matching the reference implementations) and does not violate the threat model because it is a write-only diagnostic channel. However, if the host application redirects `sys.stderr` to a file or socket, a malicious config could flood that channel. The host is responsible for providing a safe `print_sink`.

4. **The `load()` statement** is host-mediated. Without a loader, `load()` raises an error. The provided `FileLoader` reads from the filesystem, but it is only used when the host explicitly passes it. This is acceptable.

## Resource Limits

The threat model requires bounded CPU and memory consumption. **The current implementation does not enforce either limit.**

- **Step counter:** Not implemented. An infinite loop (`for i in range(10**100): pass`) or a deeply nested computation will run until the host process is killed or the Python recursion limit is hit.
- **Heap counter:** Not implemented. Expressions like `[0] * 10**9` or `"x" * 10**9` will attempt to allocate enormous amounts of memory, potentially causing an out-of-memory condition.
- **Recursion depth:** The evaluator is recursive. A malicious config that nests `if`/`for`/function calls deeply can exhaust the Python call stack (`RecursionError`). While this does not allow escape, it can crash the host process or the evaluating thread.
- **Parser depth:** The recursive-descent parser can also hit the recursion limit on deeply nested expressions.

**Assessment:** Resource exhaustion is the most significant practical risk. An adversary can degrade or crash the host process through CPU or memory exhaustion.

## Other Observations

- **Integer overflow:** Python’s arbitrary-precision `int` is used. There is no overflow, but computing `10**10**10` will consume unbounded time and memory.
- **String indexing:** Code-point indexing is used (diverging from Java’s UTF-16). This does not introduce security issues.
- **Mutability:** The `Mutability` token correctly prevents mutation after freezing. Frozen modules are read-only.
- **Recursion in user code:** The interpreter correctly forbids recursive function calls (matching the Starlark spec). This prevents unbounded recursion through user-defined functions, but does not prevent deep nesting of *non-recursive* calls or data structures.

## Recommendations

1. **Implement a step counter.** Increment a counter on every statement and backward branch; raise an uncatchable error when a configurable limit is exceeded. This is the most important missing defence.
2. **Implement a heap counter.** Charge approximate memory on every `SValue` allocation; raise when a limit is exceeded. Pre-check sizes for multiplication and repetition operations.
3. **Add depth limits.** Enforce a maximum nesting depth in the parser and evaluator (e.g., 200–500 levels) to prevent stack overflows.
4. **Audit builtin return values.** Ensure no builtin ever returns a raw Python `list`, `dict`, or `set` instead of the corresponding Starlark wrapper.
5. **Consider a subprocess sandbox** for defence-in-depth. Running each evaluation in a separate process with `resource.setrlimit` would provide hard OS-level guarantees for CPU and memory, independent of interpreter-level counters.

## Conclusion

The core sandbox boundary is well-designed and appears to prevent introspection escapes. The most urgent gap is the absence of resource limits, which leaves the host vulnerable to denial-of-service attacks. Adding a step counter and a heap counter would bring the implementation into alignment with its stated threat model.
