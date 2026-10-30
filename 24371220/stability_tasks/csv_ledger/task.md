# Aggregate a CSV sales ledger

Only modify `ledger.py`. Implement `summarize(text: str) -> list[dict]` using
standard-library Python. Parse CSV with required column names sku, quantity,
unit_price (any order; extra columns allowed). Strip header names and reject
duplicate headers or missing required names with ValueError. Empty input is
invalid; header-only input returns []. Blank physical lines are ignored by CSV.

For each data record: strip sku and reject empty; strip quantity and require an
ASCII signed integer ([+-]?[0-9]+), including zero/negative returns; strip price
and require a finite, nonnegative Decimal value (Decimal string syntax, including
scientific notation, is accepted). Missing cells or extra unnamed cells reject
the entire input with ValueError. A quoted sku may contain commas/newlines.

Aggregate quantity and exact quantity*price revenue per sku; preserve order of
first occurrence. Return dictionaries with exactly sku, quantity (int), revenue
(string with two decimal places). Round the final aggregate once per sku using
ROUND_HALF_EVEN; normalize negative zero to '0.00'. Inputs have at most 20
significant digits and exponent magnitude at most 10; no binary float arithmetic.
All invalid input raises ValueError, with no partial result. Error text is free.

Create a plan, fully read ledger.py, and run `python -m pytest -q` before writing.
After the last edit run full `python -m pytest -q`; if it passes, finish the plan
and final_answer normally. Do not modify tests or add dependencies.
