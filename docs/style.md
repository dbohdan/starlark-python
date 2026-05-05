# Writing style

For docs, READMEs, code comments, and commit messages. Built from a
copy-edit pass against a fiction-oriented unslop guide; only the
rules that survived translation to technical prose are kept.

## Word choice

**Cursed vocabulary.** These show up in AI prose more than human
prose and rarely earn their place in technical writing. Cut or
replace:

> delve, leverage, robust, streamline, harness, utilize, foster,
> pivotal, crucial, intricate, multifaceted, resonate, catalyze,
> underscore, testament, enhance, seamless, comprehensive, holistic,
> nuanced (as a compliment).

**Adverbs split into two categories.** Decorative adverbs
(`fundamentally`, `essentially`, `truly`, `remarkably`, `arguably`,
`quietly`, `deeply`) inflate ordinary statements; cut them.
Load-bearing adverbs (`intentionally`, `deliberately`, `explicitly`)
tell a future reader "this is a design choice, don't change it
without thinking" — keep them in code comments and design docs
where the signal matters; cut them in user-facing prose where
they're just emphasis.

**"Serves as" / "stands as" / "represents".** Replace with `is`.

**False ranges.** `from X to Y` only works when X and Y bound a real
spectrum. "From simple scripts to large systems" is fine; "from
caching to monitoring" isn't.

## Sentence-level

**Filler transitions.** Cut: `it's worth noting`, `notably`,
`interestingly`, `importantly`. If the next clause matters, just say
it.

**Negative parallelism.** "It's not X — it's Y", "Not X. Not Y.
Just Z." Once per document, used for real contrast. Don't reach for
it for emphasis.

**Self-answered rhetorical questions.** "The result? A clean abort."
Cut. Just write the result.

**Anaphora.** Repeating sentence openings (`We do X. We do Y. We do
Z.`) is a fiction technique. In tech writing it reads as padding.

## Structure

**Default list-of-three.** When you find yourself writing a
three-item list, ask: are there actually three things, or did I
pad? Two-item lists, four-item lists, and prose are all available.

**Lists vs prose.** A list is right when items are parallel,
scannable, and would interrupt prose flow if inlined. A list is
wrong when the items have a logical or causal relationship the
bullets hide. "I rejected approach X for three reasons:" is often
better as a paragraph that argues the case.

**Emphasis: signal vs ornament.** Bold a term that introduces it
for the first time, or marks a warning the reader must not miss.
Don't bold for tone — `**charge-only by design**` reads as
ornament; `charge-only by design` does the same work without the
visual noise. Same for italics.

**Bold-first bullets** are fine for labelled lists (parameter docs,
changelogs, error catalogues). They're not fine when every bullet
in the document opens with a bolded phrase regardless of whether
it's a label.

**Em-dashes** are useful in technical writing for parenthetical
clarification: "the unit is coarse — Starlark operations, not
Python instructions". Use them when commas would be ambiguous and
parentheses would interrupt. Don't use them as a generic dramatic
pause.

## Code comments and docstrings

**Why, not what.** Code shows what it does; comments explain why it
does it that way. "Increment counter" is noise; "Increment before
the check so re-entry doesn't re-fire the callback" is signal.

**Module docstrings document scope, not content.** A one-line
summary of what the module is responsible for, not a list of every
function it contains.

**Don't restate the signature.** `def freeze(self) -> None:
"""Freezes the module."""` is wasted text. Either explain the
contract (when does it raise, what's the post-condition) or omit
the docstring.

**Don't use prose flourishes.** "Elegantly handles the case
where..." → "Handles the case where...". Code comments are
particularly susceptible because the surrounding code is dry; prose
feels like relief, but it's just noise.

## Tone

**Match stakes to scope.** A bug fix isn't "critical" unless data
loss is on the line. A design decision isn't "fundamental" unless
reversing it would require a rewrite. Inflation devalues the words
for when you actually need them.

**No "despite its challenges" formula.** Acknowledging a problem
and then dismissing it optimistically is a tell. If a system has
limitations, state them; don't soften with "but".

**Prefer specific to grand.** "Two host threads can call
`exec_file` concurrently" beats "supports concurrent execution at
scale".

## Tests

The same rules apply to test names and docstrings.
`test_foo_works_correctly` is noise; `test_foo_rejects_negative_index`
is signal. A test docstring that restates the test name is wasted;
one that explains the failure mode it would have caught is useful.

## What this guide is **not**

- A grammar reference. Use any standard one.
- A formatter. `ruff format` handles whitespace and quotes.
- Exhaustive. The goal is to flag the patterns that come up; the
  rest is judgement.
