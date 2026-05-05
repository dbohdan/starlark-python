# Conformance xfail review

A walkthrough of the 12 conformance files currently marked xfail in
`tests/test_conformance.py`. For each file I categorize the outstanding
failures and recommend whether to fix.

Key:

- **SPEC** — a real spec compliance gap; should be fixed.
- **WORDING** — exact error-message text that the Java reference happens
  to produce. Functionally we behave the same; we just emit different
  strings. The spec doesn't mandate wording. Cheap to align if we want
  byte-equivalence with Bazel.
- **JAVA-32BIT** — Java's `StarlarkInt` rejects values outside the
  signed-32-bit range with specific messages. Inapplicable to our
  arbitrary-precision `int` model; documented divergence.
- **JAVA-UTF16** — Java indexes strings by UTF-16 code unit; we index by
  code point. Tests that depend on surrogate-pair indexing or surrogate
  ordering will never agree.
- **TEST-DRIVER** — depends on a Bazel `ScriptTest`-specific feature
  unrelated to the language spec.

## Summary

| File                    | SPEC bugs | WORDING | JAVA-32BIT | JAVA-UTF16 | TEST-DRIVER |
| ----------------------- | --------- | ------- | ---------- | ---------- | ----------- |
| `int.star`              | **1**     | many    |            |            |             |
| `string_format.star`    | **1**     | a few   |            |            |             |
| `string_misc.star`      | **1-2**   | a few   |            |            |             |
| `loop.star`             |           | many    |            |            |             |
| `int_constructor.star`  |           | many    |            |            |             |
| `float.star`            |           | many    |            |            |             |
| `function.star`         | **2**     | 1       |            |            |             |
| `sorted.star`           | **1**     | 1       |            | 1          |             |
| `set.star`              | maybe 1   | 1       |            |            |             |
| `range.star`            |           |         | all        |            |             |
| `json.star`             |           |         |            | 1          |             |
| `fields.star`           |           |         |            |            | 1           |

**Spec bugs to fix (5–6 issues across 4 files):**

1. `int.star` — `_bitwise()` error message hardcodes `|`; should print the
   actual operator. `1 & False` reports "int | bool" instead of "int & bool".
   *One-line fix.*
2. `string_format.star` — `str.format` accepts `,`, `.`, `[`, `]`, etc. inside
   field names and treats them as keyword lookups. The spec rejects them as
   "Invalid character X inside replacement field". Also doesn't currently
   detect "Cannot mix manual and automatic numbering".
   *Real fix; ~30 lines in `_format_impl`.*
3. `string_misc.star` — `str.replace(old, new, count=None)` should reject
   `None` as the count; mine treats it as "no limit".
   *One-line argument validation.*
4. `function.star` — recursion detection misses lambdas (likely because two
   lambda call sites share the same `id` after copying); needs a second
   look. Also `def f(x=[]): x.append(1)` should freeze the default after
   the function body returns ("trying to mutate a frozen list value" test).
   *Two distinct bugs in `eval/function.py`.*
5. `sorted.star` — operand order in "unsupported comparison" errors: I
   currently sort the operand types alphabetically (so `min(int, str)` and
   `min(str, int)` give the same wording), but the spec test expects the
   natural left-to-right order. Same file: the operator format is `<` where
   it should be `<=>`.
   *One-line fix in `values.less_than`.*
6. `set.star` — `json.encode(set(...))` is expected to succeed in the test;
   our encoder rejects sets. The spec doesn't define JSON encoding of sets;
   this might be a recent Java reference addition. **Recommend asking
   upstream** before adding it. Probably yes if we want to match Bazel.

**JAVA-legacy (won't fix without losing our model):**

- `range.star` — every assertion expects rejection of >2³¹ start/stop/step
  with messages like *"got 2147483648 for stop, want value in signed 32-bit
  range"*. Inapplicable to our arbitrary-precision int model. Already
  documented under the "No 32-bit-range checks" divergence in
  [`README.md`](../README.md).
- `json.star` — last failing assertion is `json.encode("😹"[:1])`; in Java
  with UTF-16 indexing, `[:1]` slices off the first surrogate half and
  produces a replacement character. With code-point indexing, `[:1]`
  returns the whole 1-codepoint emoji. Documented under the "Strings
  indexed by Unicode code point" divergence.
- `sorted.star` (residual after spec fix) — sorting strings containing
  non-BMP characters depends on UTF-16 ordering; our code-point ordering
  produces a different result.
- `fields.star` — a single assertion expects `mutablestruct(c=int)` to
  reject `s.c = "bad"` with a "bad field value" error, i.e. the
  `mutablestruct` test helper tracks the original type of each field and
  rejects type-changing assignments. This is a property of Bazel's
  ScriptTest helper, not the spec. Not worth implementing for one test.

**Pure WORDING fixes** (mechanical alignment with Bazel error strings;
none change behavior):

- `loop.star`, `int_constructor.star`, `float.star`, parts of `int.star`,
  `string_misc.star`, `string_format.star`, `function.star`,
  `set.star`, `sorted.star`.

If we wanted to land the WORDING fixes too, that's roughly a half-day of
mechanical text changes — they tend to share patterns ("got X for Y, want Z"
vs my "Y must be Z, got X"). The judgment call is whether byte-equivalent
error messages with Bazel are worth the noise in `errors.py` /
`evaluator.py` / etc.

## Per-file detail

### `int.star`

- **SPEC** `_bitwise()` returns `"... int | bool"` regardless of operator
  (line 593 of `eval/evaluator.py` hardcodes `|`).
- **WORDING** `%x`/`%X`/`%o` format-spec errors: "got string for '%x'
  format, want int or float" vs my "%x requires int, got string".

### `string_format.star`

- **SPEC** `str.format` accepts `{0,1}`, `{0.1}`, `{test.}`, `{test[}` —
  all of which the spec rejects with *"Invalid character X inside
  replacement field"*. Some of these the test expects to fail with
  "No replacement found for index N" (when the field is purely numeric
  but out of range), and *"Cannot mix manual and automatic numbering"*
  when `{}` and `{N}` co-exist.
- **WORDING** "Missing argument 'b'" vs my "missing keyword argument: b".

### `string_misc.star`

- **SPEC** `"x".replace("a", "b", count=None)` is rejected by the test;
  mine treats `None` as "no limit". Spec position: optional int args
  shouldn't accept None.
- **WORDING** `removeprefix`/`removesuffix` argument-type errors.
- One case looks like a string passed to `len()` should produce "type
  'string' is not iterable" — needs investigation.

### `loop.star`

All ~17 chunk failures are wording mismatches:

- "got 'int' in sequence assignment" (mine: "got value of type 'int',
  want 'iterable'")
- "too few values to unpack (got 0, want 2)" (mine: "unpack: got 0
  values, expected 2")
- "too many values to unpack (got 3, want 2)" (mine: "unpack: got 3
  values, expected 2")

The semantics are right; only the strings differ.

### `int_constructor.star`

24 wording failures, all in the same family:

- `int(None)` — mine "int() does not accept NoneType", expected "got
  value of type 'NoneType', want 'string, bool, int, or float'"
- `int("")` — mine "int() invalid literal: ''", expected "empty string"
- `int("0xFF", 8)` — mine "invalid literal for int() with base 8:
  '0xFF'", expected "invalid base-8 literal: \"0xFF\""

### `float.star`

14 wording failures plus one minor real fix:

- **WORDING** `int(nan)` — mine "cannot convert float NaN to integer"
  is actually Python's stdlib message leaking through; I should catch
  it.
- **WORDING** `len(0.5)` should fail with "parameter 'x' got value of
  type 'float', want 'iterable or string'".
- **SPEC-ish** "floating-point modulo by zero" vs "integer modulo by
  zero" — we lump them. Spec is silent but the differentiation is
  helpful.

### `function.star`

- **SPEC** Lambda recursion not detected. I track `id(StarlarkFunction)`
  in `Thread.active`, but Python may reuse object ids after gc, and
  lambdas in some patterns can share them. Need a token-based check.
- **SPEC** Default argument values should be frozen at function-creation
  time; we don't, so `def f(x=[]): x.append(1)` mutates the default
  forever.
- **WORDING** `dict.pop()` with no args leaks Python's TypeError
  ("d_pop() missing 1 required positional argument: 'key'"). Need a
  shim that translates the right error.

### `sorted.star`

- **SPEC** "unsupported comparison: bool <=> int" expected, mine "bool <
  int". Use `<=>` everywhere, not the literal operator.
- **SPEC** Operand order in error: my `less_than` sorts the type names
  alphabetically before formatting, so `min(int, str)` and `min(str,
  int)` get the same message. The test depends on natural left-right
  order. Should revert the sort.
- **JAVA-UTF16** Sorting `"🌿"` and other non-BMP strings: code-point
  ordering vs UTF-16-code-unit ordering disagree.

### `set.star`

- **SPEC** (debatable) `json.encode(set(...))` — test expects the encoder
  to accept sets and produce `[1,2,3]`. Spec doesn't say. Recent Bazel
  addition? **Recommend checking upstream** before adopting.
- **WORDING** "accepts no more than 1 positional argument" — Python
  TypeError leak from `b_set(*args)` with two positionals. Same
  shim pattern as `function.star`.

### `range.star`

All 4 failures are 32-bit-range rejections that don't apply to us.
**Recommend keeping xfail**; covered by README divergence note.

### `json.star`

- **SPEC** "maximum recursion depth exceeded in __instancecheck__" on
  the very large encode test (`for x in range(100000)`). The encoder
  is recursive in Python; could be made iterative. Worth fixing for
  robustness.
- **JAVA-UTF16** `json.encode("😹"[:1])` expected to be the 0xFFFD
  replacement char; we emit the full emoji. Documented divergence.

### `fields.star`

- **TEST-DRIVER** Single failure: `mutablestruct` rejects a type-changing
  reassignment with "bad field value". This is a property of Bazel's
  test helper, not Starlark. **Not worth implementing.**

## Recommendation

If you want a single 1-day push to maximize green:

1. Land the 5 spec-compliance fixes (`int.star`, `string_format.star`,
   `string_misc.star`, `function.star`, `sorted.star`). Estimated +3
   files green, partial improvement to 2 more.
2. Decide on `set.star`'s `json.encode(set)` after checking upstream.
3. Land the wording alignment for `loop.star` and `int_constructor.star`
   if you want a higher pass rate. Estimated +2 files green.

That would put us at **31–33 of 38** (82–87%).

The remaining 5–7 files (`range.star`, `json.star`, `sorted.star` UTF-16
residual, `float.star` partial, `fields.star`, plus any wording we don't
align) are JAVA-32BIT / JAVA-UTF16 / TEST-DRIVER and shouldn't change
without abandoning our `int`/`str` model.
