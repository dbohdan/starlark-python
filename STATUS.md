# Status

A journal. Append-only. Newest entries at the top.

## 2026-05-04 — Bootstrap complete

What landed:

- Pruned the fork: deleted everything Bazel-specific. Java sources moved to
  `reference/`, `.star` conformance files copied to `conformance/`. History
  squashed to a single orphan commit; `.git` shrunk from ~30M to ~700K.
- `pyproject.toml` with hatchling backend, no runtime deps, `pytest` and
  `ruff` as dev deps. `python_requires >= 3.11`. `pytest` configured to find
  `tests/` and put `src/` on the import path.
- Scaffolded `src/starlark/{,syntax/,eval/}` with stub `__init__.py` files.
- `tests/test_smoke.py`: import test passes; eval test xfails strict (will
  flip to passing in Phase 6).
- `ROADMAP.md` with 14 phases, Java references, and conformance unlocks.
- `README.md` calling out the two intentional divergences (Python `int`,
  code-point-indexed strings).

What's next: Phase 1 — Lexer. Read `reference/.../syntax/Lexer.java` end to
end first.

### Notes / clarifications, not Decisions Pending

- The conformance `.star` files in this repo are written for Bazel's
  `ScriptTest`, which **predeclares** `assert_eq`/`assert_`/`assert_fails`/
  `freeze`/`struct`/`mutablestruct`/`int_mul_slow` as builtins. They do
  **not** use `load("assert.star", "asserts")` like starlark-go's testdata.
  Phase 7 will provide them as predeclared functions to match. Phase 12
  (`assert.star` module) stays in the roadmap as a placeholder for the
  load form, in case any test we add later needs it.
- Bazel-only token kinds (`CAST`, `ISINSTANCE`, `ELLIPSIS`, `RARROW`,
  `CLASS`, `IMPORT`, `EXCEPT`, `FINALLY`, `TRY`, `WITH`, `YIELD`, `RAISE`,
  `AS`, `FROM`, `GLOBAL`, `NONLOCAL`, `ASSERT`, `DEL`) are reserved keywords
  in Java's lexer but not legal in Starlark per the spec. We'll lex them
  as identifiers (or only as keywords in error positions) per the
  spec.md guidance — to be confirmed in Phase 1.
- Doc-comment tokens (`#:`) are a Bazel-specific extension. Skipped.

## Decisions Pending

(none)
