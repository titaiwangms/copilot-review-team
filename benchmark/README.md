# Catch-rate benchmark (proof of concept)

**Status: proof-of-concept gate.** This benchmark answers the question the rest of
the repo's CI never asks: *does the review team actually catch defects?*

The repo's `scripts/validate.sh` checks **tidiness** — frontmatter shape, model
sync, reviewer-count phrasing, shell syntax. None of those checks tell you whether
the reviewers would flag a real bug. "Best review team" is therefore unfalsifiable.
This benchmark makes it falsifiable on a small, labeled corpus, so we can decide
whether a fully trusted version is worth building before investing in it (and
before acting on [#10](../../../issues/10), collapsing 9 agents → 5, which this POC
gates: don't cut a reviewer until you can measure what cutting it costs).

## What it measures

Given a corpus of code diffs with **known, planted defects** and a description of
the **expected finding** for each, the harness reports:

- **Catch-rate** — `caught / total planted defects` (per fixture and overall).
- **Misses** — planted defects no reviewer flagged.
- **False positives** — Major/Critical findings raised against the **clean
  control** fixture, which has no real defect.

A catch is recorded when any of a defect's `match_any` keywords appears in the
reviewer's output. Keyword lists live in each fixture's `expected.json`, so
tuning sensitivity is a data edit, not a code change.

## Layout

```
benchmark/
  README.md                 this file
  run_benchmark.py          harness: collect reviews, score, print a scorecard
  score.py                  pure scoring logic (no I/O / subprocess) — unit tested
  test_score.py             co-located unit tests for the scorer
  fixtures/
    001-sql-injection/      each fixture is a directory:
      diff.patch              the change under review (a unified diff)
      expected.json           planted defect(s) + match keywords
    002-command-injection/
    003-hardcoded-secret/
    004-none-deref/
    005-off-by-one/
    006-resource-leak/
    007-clean-control/      no planted defect — measures false positives
```

The corpus spans security defects (SQL injection, command injection, hardcoded
secret), correctness defects (unchecked `None`, off-by-one), a reliability defect
(leaked file handle), and one deliberately clean change.

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
      "match_any": ["sql injection", "parameterized", "injection"]
    }
  ]
}
```

A fixture with an empty `defects` list is a **clean control**.

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
once per fixture; the unified diff is piped on **stdin**, and two environment
variables are set: `BENCHMARK_DIFF` (path to the diff) and `BENCHMARK_FIXTURE_ID`.
Whatever the command prints to **stdout** is captured as the review.

```bash
# Toy reviewer (pattern match) — just to show the wiring:
python3 benchmark/run_benchmark.py --reviewer-cmd \
  'grep -qi "shell=True" "$BENCHMARK_DIFF" && echo "- Critical: command injection"'
```

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

fixture                defects  caught  result
----------------------------------------------
001-sql-injection      1        1/1     ALL CAUGHT
...
007-clean-control      0        -       clean (no false positives)

== Summary ==
  fixtures scored : 7
  catch-rate      : 83% (5/6)
  defects missed  : 1
  false positives : 0 (on clean control)
```

Add `--json` for machine-readable output. **Exit code:** `0` when every planted
defect was caught, `2` when any defect was missed (so the benchmark can gate CI
later), and `1` on a usage/corpus error.

## Known limitations (this is a POC, not ground truth)

These are the tar-pits the architect's triage flagged for [#9](../../../issues/9).
They are why this is gated as a proof of concept rather than wired into CI today:

- **Keyword matching is shallow.** A catch means a keyword appeared, not that the
  reviewer truly understood the defect. A reviewer could "catch" by luck, and a
  correct finding worded unusually could be scored as a miss. The fixture id is
  stripped from the review text before matching so an echoed id can't fake a catch
  (see `strip_fixture_id`), but the keyword lists still need human curation.
- **False-positive scoring is heuristic.** The clean control flags lines that look
  like Major/Critical findings (bulleted/bolded severity labels); it surfaces the
  offending lines for human confirmation rather than asserting they are wrong.
  Minor/Nit suggestions on clean code are not penalized.
- **Small corpus.** Seven fixtures is enough to prove the mechanism, not to make
  statistically meaningful claims. A trusted version needs 15–30+ fixtures across
  more languages and defect classes.
- **Model drift.** Live reviewer results will vary run to run; treat a single run
  as a sample, not a fixed score.
- **Corpus licensing/privacy.** All fixtures here are synthetic and original. Any
  expansion using real-world diffs must respect source licensing and avoid
  embedding private code or real secrets.

## Adding a fixture

1. Create `benchmark/fixtures/<NNN-short-name>/`.
2. Add `diff.patch` (a realistic unified diff containing the planted defect).
3. Add `expected.json` using the format above. List several `match_any` keywords
   that a competent reviewer would naturally use when describing the defect; keep
   them specific enough that unrelated prose won't match.
4. Run `python3 benchmark/test_score.py` — the corpus-integrity tests will load and
   validate your fixture and fail loudly if it is malformed.
