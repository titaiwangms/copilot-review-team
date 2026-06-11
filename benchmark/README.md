# Catch-rate benchmark (proof of concept)

**Status: proof of concept.** This benchmark answers the question the rest of
the repo's CI never asks: *does the review team actually catch defects?*

The repo's `scripts/validate.sh` checks **tidiness** — frontmatter shape, model
sync, reviewer-count phrasing, shell syntax. None of those checks tell you whether
the reviewers would flag a real bug. "Best review team" is therefore unfalsifiable.
This benchmark makes it falsifiable on a small, labeled corpus, so we can decide
whether a fully trusted version is worth building before investing in it. It is
**directly relevant** to [#10](../../../issues/10) (collapsing 9 agents → 5): it
provides the measurement primitive — and a config-comparison mode — for asking
"what does cutting a reviewer cost?". It does **not** by itself gate that decision:
a defensible gate needs the trusted, larger, balanced corpus described under
[Known limitations](#known-limitations-this-is-a-poc-not-ground-truth). Treat the
numbers as evidence to inform #10, not as an automated gate.

## What it measures

Given a corpus of code diffs with **known, planted defects** and a description of
the **expected finding** for each, the harness reports:

- **Catch-rate** — `caught / total planted defects` (per fixture and overall).
- **Misses** — planted defects no reviewer flagged.
- **False positives** — a fabricated finding that asserts a concrete **located**
  defect (a Major/Critical severity assertion naming a code location) against a
  **control** fixture (a clean change or near-miss), which has no real defect. A
  clean sign-off that names no code ("## Critical: all clear", "looks good") is
  **not** a false positive — see [What counts as a false positive](#what-counts-as-a-false-positive).

### What counts as a catch

A naive "does any keyword appear?" test is trivially gameable: a reviewer that
emits a constant blob of defect keywords without reading the code would score a
perfect catch-rate, defeating the whole point (making review quality
*falsifiable*). So a defect is **caught** only when the review contains, inside a
single block (paragraph), **all** of:

1. one of the defect's specific `match_any` **phrases** — multi-word and
   defect-specific (e.g. `"sql injection"`, `"parameterized query"`), not bare
   nouns like `"injection"` that show up in unrelated prose; **and**
2. that phrase in a **non-negated** context — "there is no SQL injection here"
   does not count as catching the SQL-injection defect; **and**
3. a **location** reference — one of the defect's `location_tokens` (the function
   name or file from the diff) — within ~160 characters of the phrase.

Requirement 3 is the key anti-gaming property: to ground a catch the reviewer
must cite the symbol/file it was handed, i.e. it must actually have read the
change. Citing `file:line` / the symbol is exactly what real reviewers (and this
repo's reviewer agents) are told to do, so this rewards genuine findings and
rejects keyword splatter. Phrase and location lists live in each fixture's
`expected.json`, so tuning a match is a data edit, not a code change.

### What counts as a false positive

A false positive uses the **same grounding principle** as a catch, applied to a
clean control: it is a fabricated finding that asserts a concrete **located**
defect on code that has none. A control line is counted only when it has **both**:

1. a **Major/Critical severity assertion** — line-leading (incl. markdown
   headings/bullets, e.g. `## Critical:`, `- Major:`) or inline-emphasized
   (`**Critical**`), in a non-negated context; **and**
2. a **non-negated code-location reference** — a filename (`users.py`), a
   `` `backticked` `` token, a `call()`, a `snake_case`/`dotted.path` symbol, or a
   line number — the structural shape of pointing *at* code.

This is deliberately **structural**, not a word list. The consequences:

- **Clean sign-offs are not false positives.** "## Critical: all clear", "looks
  good", "- Major: none of note" cite no code, so they are not located findings.
  Scoring them as false positives would punish a reviewer for *correctly* declining
  to flag clean code — the exact behaviour we want. There is **no absence/sign-off
  vocabulary** to maintain (the recurring source of bypasses); the grounded
  definition handles every phrasing for free.
- **Vague, locationless severity assertions are unscored, not penalized.**
  "## Critical: imagined bug" is not a falsifiable finding, so it is not a false
  positive. A reviewer that only emits such prose also earns **zero catches**
  (catches require grounding too), so it fails the benchmark on **recall** instead.
  Precision and recall are a pair: "be vague to be safe" is a losing strategy.
- **Placement dodges are closed structurally.** Because the *located reference* is
  what is graded, a fabricated finding cannot escape by attaching a bare "none" in
  any position ("Critical: none. SQL injection in `find_user_by_name`"); the
  located reference is still asserted, so it still counts.
- Minor/Nit suggestions on clean code are not penalized.

A corpus-grounded companion check additionally flags the specific case where the
located defect matches a *known planted defect* asserted on a control (reusing the
catch logic directly), giving a precise per-defect message.

## Layout

```
benchmark/
  README.md                 this file
  run_benchmark.py          harness: collect reviews, score, print a scorecard
  score.py                  pure scoring logic (no I/O / subprocess) — unit tested
  test_score.py             co-located unit tests for the scorer
  test_run_benchmark.py     co-located unit tests for the harness
  fixtures/
    001-sql-injection/      each fixture is a directory:
      diff.patch              the change under review (a unified diff)
      expected.json           planted defect(s) + match phrases + location tokens
    002-command-injection/
    003-hardcoded-secret/
    004-none-deref/
    005-off-by-one/
    006-resource-leak/
    007-clean-control/      no change of concern — measures false positives
    008-clean-parameterized-query/  near-miss control (looks like 001, but safe)
    009-clean-subprocess-list/      near-miss control (looks like 002, but safe)
    010-clean-with-open/            near-miss control (looks like 006, but safe)
```

The corpus spans security defects (SQL injection, command injection, hardcoded
secret), correctness defects (unchecked `None`, off-by-one), a reliability defect
(leaked file handle), and **four controls**: one plainly-clean change plus three
**near-misses** that touch the same APIs as a defect fixture but are actually
correct (a parameterized query, a `subprocess` argument list, a `with open`).
Near-misses measure *precision* — they catch a trigger-happy reviewer that flags
"SQL injection" whenever it sees SQL.

### Fixture format (`expected.json`)

```json
{
  "id": "001-sql-injection",
  "title": "SQL injection via string-concatenated query",
  "language": "python",
  "defects": [
    {
      "id": "sqli",
      "category": "security",
      "severity": "critical",
      "location": "app/users.py:find_user_by_name",
      "description": "Human-readable explanation of the planted defect.",
      "match_any": ["sql injection", "parameterized query", "bound parameter"],
      "location_tokens": ["find_user_by_name", "users.py"]
    }
  ]
}
```

**Required** keys on each defect (the scorer rejects a fixture that omits them):

- `id` — unique within the fixture.
- `category`, `severity` — labels for reporting.
- `match_any` — non-empty list of specific phrases; a catch needs one of them.
- `location_tokens` — non-empty list of symbols/filenames; a catch must cite one
  near the phrase. This is what makes a catch a *located* finding.

**Optional** keys: `location` (human-readable `file:symbol`, for documentation),
`description` (prose explanation). A top-level **`note`** documents a control's
intent (why a near-miss is actually safe) and is ignored by the scorer.

A fixture with an empty `defects` list is a **control**; add a `note` explaining
what makes it clean (especially for a near-miss).

## Running it

Requires only `python3` (standard library), matching the rest of `scripts/`.

**Inspect the corpus (no reviewer needed):**

```bash
python3 benchmark/run_benchmark.py
```

**Score reviews you collected by hand or from another tool:**

Put one file per fixture, named `<fixture-id>.md` (or `.txt`), in a directory:

```bash
python3 benchmark/run_benchmark.py --review-dir path/to/reviews
```

**Drive a reviewer live** with `--reviewer-cmd`. The harness runs the command
once per fixture; the unified diff is piped on **stdin**. To avoid leaking the
answer key, the command is **not** told which fixture it is reviewing — instead
it receives `BENCHMARK_DIFF` (path to a temp copy of the diff with an opaque
filename) and `BENCHMARK_FIXTURE_TOKEN` (a random per-run token). The
human-readable fixture id is never exposed (any inherited `BENCHMARK_FIXTURE_ID`
is stripped), so a reviewer cannot special-case a fixture or tell which one is the
control. Whatever the command prints to **stdout** is captured as the review.

```bash
# Toy reviewer (pattern match) — just to show the wiring:
python3 benchmark/run_benchmark.py --reviewer-cmd \
  'grep -qi "shell=True" "$BENCHMARK_DIFF" && echo "- Critical: command injection"'
```

> **Security:** the harness itself never executes fixture code — it only passes
> the diff to your command as *data* (on stdin and as a file at `$BENCHMARK_DIFF`).
> The fixtures contain planted attack payloads (e.g. a `shell=True` command
> injection, a `; rm -rf` shape), so a `--reviewer-cmd` that `eval`s, sources, or
> otherwise *executes* the piped diff would be running those payloads. Keep the
> reviewer command read-only: parse the diff, don't run it.

**Compare configurations** (the measurement primitive relevant to
[#10](../../../issues/10) — see the status note: this informs the decision, it
does not automate it). Pass `--config NAME=SPEC` repeatedly, where `SPEC` is
`cmd:<command>` or `dir:<path>`. The harness scores each configuration and prints
a side-by-side table plus deltas vs. the first one — so "what does cutting a
reviewer cost?" becomes a measured number, not a guess:

```bash
python3 benchmark/run_benchmark.py \
  --config "nine=dir:reviews/nine-agent" \
  --config "five=dir:reviews/five-agent"
```

`--reviewer-cmd` / `--review-dir` are shorthands for a single
`--config default=...`.

### Wiring a Copilot CLI review agent

The reviewer command is any program that reads a diff and emits review text, so a
Copilot CLI reviewer agent (e.g. `local-code-reviewer`) can be plugged in once you
have a non-interactive invocation that takes the diff on stdin and prints the
review to stdout. Sketch:

```bash
python3 benchmark/run_benchmark.py --reviewer-cmd \
  'copilot --agent local-code-reviewer -p "Review this diff. Report findings by severity." < "$BENCHMARK_DIFF"' \
  --save-reviews /tmp/benchmark-reviews
```

`--save-reviews <dir>` writes each captured review to `<dir>/<fixture-id>.md` so
you can inspect or re-score them later with `--review-dir`. Adjust the flags to
match your installed Copilot CLI; the harness only cares that the command prints
the review to stdout.

### Output

```
== Catch-rate benchmark ==

fixture                        defects  caught  result
------------------------------------------------------
001-sql-injection              1        1/1     ALL CAUGHT
...
007-clean-control              0        -       clean (no false positives)
008-clean-parameterized-query  0        -       clean (no false positives)

== Summary ==
  fixtures scored : 10
  catch-rate      : 83% (5/6)
  defects missed  : 1
  false positives : 0 (on clean/near-miss controls)
```

With two or more `--config`s the harness prints a comparison table instead:

```
== Catch-rate comparison ==

configuration        catch-rate       missed   false-pos
--------------------------------------------------------
nine                 100% (6/6)       0        0
five                 83% (5/6)        1        0

== Deltas vs 'nine' ==
  five               catch-rate -17 pts, false-positives +0
```

Add `--json` for machine-readable output. **Exit code** (single configuration):
`0` only when every planted defect was caught **and** no false positive was raised
on a control; `2` when any defect was missed **or** any control drew a
Major/Critical false positive (so CI fails on both a reviewer that misses defects
*and* a splatter reviewer that over-flags clean code); `1` on a usage/corpus
error. Comparison runs are informational and exit `0` unless the corpus itself
fails to load.

## Known limitations (this is a POC, not ground truth)

These are the tar-pits the architect's triage flagged for [#9](../../../issues/9).
They are why this is gated as a proof of concept rather than wired into CI today:

- **Matching is phrase + location, not comprehension.** A catch means a specific
  phrase appeared, non-negated, next to a cited location — strong evidence the
  reviewer read the diff, but still not proof it *understood* the defect. A correct
  finding worded entirely outside the `match_any`/`location_tokens` vocabulary can
  still score as a miss, so the lists need human curation.
- **Residual answer-key attack.** Requiring a located, specific phrase defeats a
  constant keyword blob (it can't cite per-fixture symbols) and the old
  fixture-id leak. Two residual attacks remain, each closed by a *different* guard:
  (1) a **splatter** reviewer that emits located findings for every fixture
  (including controls) needs no reading at all — it is caught purely by the
  false-positive count on the controls, which is exactly why the single-config
  exit gate fails on false positives, not just misses. Because that count is
  **grounded** (see below), attaching an "absence" word to the fabricated finding
  does not suppress it; (2) a **determined**
  attacker could read every diff and assemble a per-fixture key (correct symbol +
  phrase adjacency) — but that requires actually reading the code, which is the
  behavior we want. Mitigations for a trusted version: opaque/rotating fixture ids
  (the harness already withholds the id and uses a random per-run token), a private
  held-out corpus, and periodic fixture rotation.
- **False-positive scoring is grounded, not a word list.** On a control the
  benchmark counts a false positive only for a fabricated **located** finding: a
  Major/Critical severity assertion plus a non-negated code-location reference
  (see [What counts as a false positive](#what-counts-as-a-false-positive)). This
  is the *same* grounding the catch side uses, so the precision gate and the recall
  gate share one principle. A corpus-grounded companion (`find_fabricated_findings`)
  additionally flags the case where the located defect matches a *real planted
  defect* — the same located, non-negated phrase that would count as a catch on the
  planted fixture — which is the primary anti-gaming guard: attaching an "absence"
  word ("Critical: none. SQL injection in `find_user_by_name` …") cannot suppress
  it, because the located reference is still graded. Crucially, there is **no
  absence/sign-off vocabulary** anywhere: a clean sign-off naming no code ("##
  Critical: all clear") is simply not a located finding, so it is never a false
  positive. A purely vague, locationless severity claim is unscored as a false
  positive (it is unfalsifiable) — but such a reviewer scores zero catches and
  fails on recall instead. Minor/Nit suggestions on clean code are not penalized.
- **Negation handling is shallow.** A short window before the phrase is scanned for
  negation cues; unusual phrasing ("hardly a real injection") may slip through.
  Phrase specificity and location grounding are the primary defenses; negation is a
  secondary guard.
- **Small corpus.** Ten fixtures (6 defects, 4 controls) is enough to prove the
  mechanism, not to make statistically meaningful claims. A trusted version needs
  15–30+ fixtures across more languages and defect classes, and a tighter
  defect-to-control balance.
- **Model drift.** Live reviewer results will vary run to run; treat a single run
  as a sample, not a fixed score.
- **Corpus licensing/privacy.** All fixtures here are synthetic and original. Any
  expansion using real-world diffs must respect source licensing and avoid
  embedding private code or real secrets.

## Adding a fixture

1. Create `benchmark/fixtures/<NNN-short-name>/`.
2. Add `diff.patch` (a realistic unified diff containing the planted defect).
3. Add `expected.json` using the format above. For each defect, list several
   `match_any` **phrases** a competent reviewer would naturally use (specific
   enough that unrelated prose won't match) and the `location_tokens` (function
   name and/or filename) the reviewer must cite. For a control, use an empty
   `defects` list and a `note` explaining why it is clean.
4. Run `python3 benchmark/test_score.py && python3 benchmark/test_run_benchmark.py`
   — the corpus-integrity tests load and validate your fixture (and confirm each
   defect is catchable by a review of its own description) and fail loudly if it is
   malformed.
