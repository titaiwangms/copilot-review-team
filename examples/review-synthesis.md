# Review synthesis — input validation for `parse_csv_row`

*Sample synthesis the lead produces after the review fan-out. Illustrative, not
an actual run.* It consolidates the five reviewers (`readability`, `code`,
`critical`, `deep`, `integration`) plus `qa-tester`, deduplicates overlapping
findings, and groups by severity. In-scope findings go back to the developer;
out-of-scope items are listed under "Follow-up suggestions."

Change under review: validation gate added to `parse_csv_row` per the
[architect design doc](architect-design-doc.md).

## Critical

- **Batch reader swallows the new error and keeps a partial record.**
  `src/parsing/reader.py:48` — the `try/except RowValidationError` appends the
  error to the report but then falls through to `records.append(record)`, where
  `record` is the value from the *previous* successful iteration (loop variable
  reuse). Result: a rejected row silently duplicates the prior row.
  *(critical-reviewer; confirmed by qa-tester repro below.)*
  - **QA repro** (`qa-tester`): input `id,name,total\n1,a,10\n2,b` →
    expected 1 record + 1 error; actual 2 records, the second a duplicate of the
    first. `pytest tests/test_csv.py::test_short_row_is_rejected` fails.

## Major

- **Required-empty check uses `not cell` instead of `cell.strip()`.**
  `src/parsing/csv.py:71` — a cell of `"   "` passes the required check, which
  contradicts the design's "empty iff `cell.strip() == ''`" decision.
  *(deep-reviewer, citing the design doc Risks section; code-reviewer flagged the
  same line independently — deduped.)*
- **`row_number` not threaded from the reader.**
  `src/parsing/reader.py:41` — calls `parse_csv_row(line, schema)` without the
  index, so every `RowValidationError` reports `row_number=0`, making the error
  report useless for locating the bad line. *(integration-reviewer.)*

## Minor

- **`RowValidationError` is not exported.** `src/parsing/__init__.py` — the design
  lists it as a public export but it is missing, so callers must reach into the
  submodule to catch it. *(integration-reviewer.)*
- **`problems` list builds full strings eagerly even on the happy path.**
  `src/parsing/csv.py:64` — minor; only matters for very large batches. Consider
  short-circuiting when valid. *(code-reviewer.)*

## Nit

- **Error message punctuation/casing inconsistent** with the rest of the module
  (`src/parsing/csv.py:80` uses "Row invalid:" vs. the codebase's lowercase
  style). *(readability-reviewer.)*

---

## Disposition

Sent back to `local-developer` (round 1 of max 2): the Critical, both Major, and
the export Minor — all in-scope for "add input validation." The Nit is bundled in
since it is a one-word fix in a line already being touched.

## Follow-up suggestions (out of scope — not sent back)

- **RFC-4180 quoted commas** are still unhandled; arity validation will reject
  legitimately-quoted rows. Worth a separate issue. *(critical-reviewer,
  deep-reviewer — agreed this is pre-existing and out of scope.)*
- **Happy-path allocation** in `parse_csv_row` could be tightened, but only
  matters at large batch sizes; defer unless profiling says otherwise.
