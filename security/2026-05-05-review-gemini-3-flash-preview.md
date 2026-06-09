# Security Review of the Starlark Implementation (Gemini)

> **Superseded.** This review predates the resource-limit implementation
> (step counter, heap counter, `MAX_CONTAINER_ELEMENTS`, `MAX_NESTING_DEPTH`,
> `MAX_INT_BITS`, and value-level depth bounding). Its "Resource Exhaustion
> (Critical Gap)" / "no step/heap counter" finding is stale; see
> [`threat-model.md`](threat-model.md) for the current state. Retained for
> historical context.

**Date:** 2026-05-05  
**Reviewer:** Gemini (Expert Software Developer)  
**Scope:** Pure-Python Starlark interpreter implementation.

## Threat Model Alignment

The project aims to provide a sandboxed environment for untrusted configurations.

### 1. Action Isolation (Success)
- **Filesystem/Network:** The interpreter does not provide built-ins for I/O. `load()` is host-mediated via a `Loader` protocol. The default `FileLoader` is only active if explicitly instantiated and passed by the host.
- **Subprocesses:** No built-ins exist to trigger shell commands or process creation.
- **Introspection:** The implementation uses a disjoint object graph. Attribute access is strictly controlled via `methods.py` and `_attr_get` in `evaluator.py`. It does not use Python's `getattr` on user-controlled objects, effectively blocking access to `__class__`, `__subclasses__`, etc.

### 2. Resource Exhaustion (Critical Gap)
The implementation currently lacks internal mechanisms to bound resource consumption, which is a requirement of the stated threat model.

- **CPU Bounding:** There is no step counter. While recursion is forbidden for user-defined functions (Phase 10), a simple `for` loop over a large `range()` can execute indefinitely.
- **Memory Bounding:** There is no heap counter. Operations like `[0] * 10**8` or large string concatenations can trigger host OOM (Out-Of-Memory).
- **Stack Safety:** Both the parser (`parser.py`) and the evaluator (`evaluator.py`) rely on Python's native recursion. Deeply nested expressions or structures will raise `RecursionError`, crashing the evaluation thread.

### 3. Data Model Integrity (Success)
- **Mutability:** The `Mutability` token implementation correctly prevents modification of frozen collections.
- **Types:** Using Python natives for immutable types (`int`, `str`) is safe, provided that arithmetic operations (like power) are eventually capped.

## Specific Risks & Recommendations

### High Risk: Built-in Return Values
Built-ins in `builtins.py` and `collection_methods.py` must never return raw Python `list`, `dict`, or `set` objects.
- **Observation:** Current implementation is diligent (e.g., `d_keys` wraps in `StarlarkList`).
- **Recommendation:** Add a decorator or automated check to ensure all builtin outputs are either primitives or Starlark wrappers.

### High Risk: Large Allocations
- **Observation:** `_check_repeat_size` in `evaluator.py` provides a soft limit (`16M` elements), but this is not applied globally to all sequence-producing operations.
- **Recommendation:** Implement a centralized `Heap` manager as discussed in design notes to charge for all allocations.

### Medium Risk: Print Flooding
- **Observation:** `b_print` writes directly to `sys.stderr`.
- **Recommendation:** Allow the host to provide a `print_sink` with a character limit to prevent log-flooding DoS.

## Conclusion
The sandbox architecture is robust against **privilege escalation** and **introspection escapes**. However, it is currently vulnerable to **Denial of Service (DoS)** via CPU and memory exhaustion. To meet the threat model, a step counter and heap allocation limits must be implemented.
