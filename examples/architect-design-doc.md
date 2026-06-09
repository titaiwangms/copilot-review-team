# Design doc — input validation for `parse_csv_row`

*Sample output from `local-architect`. Illustrative, not an actual run.*

**Task (restated):** Add input validation to `parse_csv_row(line, schema)` in
`src/parsing/csv.py` so malformed rows fail with a clear error instead of
producing silently-wrong records or raising opaque `IndexError`s downstream.

## Problem

`parse_csv_row` currently splits a raw line on commas and zips the cells against
`schema.fields` positionally. It assumes:

- the cell count always equals the field count, and
- every cell is non-empty when the field is marked `required`.

Both assumptions break on real input. A short row (`"a,b"` against a 3-field
schema) yields a record missing its last key, and a downstream `record["total"]`
then raises `KeyError` far from the actual cause. There is no single place that
states "a row is valid iff …", so the contract is implicit and untested.

## Approach

Introduce one validation gate at the top of `parse_csv_row`, before any record
is constructed. Keep it pure (no I/O, no logging) so it is trivially testable and
so callers decide how to surface failures.

- Validate **arity** (cell count == field count) and **required-but-empty** cells.
- On failure, raise a new `RowValidationError` carrying the row number, the
  offending field name(s), and the raw line — enough for a caller to log a useful
  message.
- Do not attempt type coercion here; that stays a separate concern in
  `coerce_cell`. This change is strictly "is the row well-formed?".

## Interface

```python
class RowValidationError(ValueError):
    """Raised when a CSV row does not satisfy its schema."""
    def __init__(self, row_number: int, line: str, problems: list[str]) -> None: ...

def parse_csv_row(line: str, schema: Schema, row_number: int = 0) -> dict[str, str]:
    """Parse one CSV line into a record. Raises RowValidationError if the row
    does not match `schema` (wrong cell count, or a required cell is empty)."""
```

`row_number` is a new optional parameter (defaults to `0`) so existing single-row
callers keep working; the batch reader passes the real index.

## Affected files

- `src/parsing/csv.py` — add `RowValidationError`, add the validation gate, thread
  `row_number` through.
- `src/parsing/__init__.py` — export `RowValidationError`.
- `src/parsing/reader.py` — pass `row_number` from the enumerate loop; catch
  `RowValidationError` and accumulate into the existing error report.
- `tests/test_csv.py` — new cases (see Risks).

## Risks / open questions

- **Behavior change for short rows.** Code that today silently gets a partial
  record will now get an exception. That is the intent, but any caller relying on
  the old lenient behavior needs the `try/except` in `reader.py`. Searched for
  other callers — only `reader.py` consumes this function.
- **Quoted commas.** This parser does not handle RFC-4180 quoting (commas inside
  quotes). Validation does not make that worse, but arity checks will reject a
  quoted-comma row that "should" be valid. Out of scope here; flag as follow-up.
- **Empty vs. whitespace.** Decide whether `"   "` counts as empty for a required
  field. Proposal: treat a cell as empty iff `cell.strip() == ""`. Confirm with
  the user if surprising.
