"""Aggregate a CSV sales ledger."""

import csv
import io
import re
from decimal import Decimal, ROUND_HALF_EVEN, localcontext

REQUIRED_COLUMNS = ("sku", "quantity", "unit_price")

_INTEGER = re.compile(r"[+-]?[0-9]+\Z")
_CENT = Decimal("0.01")
_PRECISION = 500


def summarize(text):
    """Aggregate quantities and exact revenue per sku, in first-seen order."""
    if not isinstance(text, str):
        raise ValueError("input must be a string")
    if not text:
        raise ValueError("empty input")

    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as exc:
        raise ValueError("invalid CSV: %s" % exc) from None

    position = 0
    header = None
    while position < len(rows):
        row = rows[position]
        position += 1
        if row:
            header = row
            break
    if header is None:
        raise ValueError("missing header row")

    names = [cell.strip() for cell in header]
    seen = set()
    for name in names:
        if name in seen:
            raise ValueError("duplicate column name: %r" % (name,))
        seen.add(name)

    columns = {}
    for name in REQUIRED_COLUMNS:
        if name not in seen:
            raise ValueError("missing required column: %s" % name)
        columns[name] = names.index(name)

    width = len(names)
    order = []
    quantities = {}
    revenues = {}

    with localcontext() as ctx:
        ctx.prec = _PRECISION
        for row in rows[position:]:
            if not row:
                continue
            if len(row) != width:
                raise ValueError(
                    "expected %d cells, got %d" % (width, len(row))
                )

            sku = row[columns["sku"]].strip()
            if not sku:
                raise ValueError("empty sku")

            quantity_text = row[columns["quantity"]].strip()
            if _INTEGER.match(quantity_text) is None:
                raise ValueError("invalid quantity: %r" % (quantity_text,))
            quantity = int(quantity_text)

            price_text = row[columns["unit_price"]].strip()
            try:
                price = Decimal(price_text)
            except (ArithmeticError, ValueError):
                raise ValueError("invalid unit price: %r" % (price_text,)) from None
            if not price.is_finite() or price < 0:
                raise ValueError("invalid unit price: %r" % (price_text,))

            revenue = price * quantity
            if sku in revenues:
                quantities[sku] += quantity
                revenues[sku] += revenue
            else:
                quantities[sku] = quantity
                revenues[sku] = revenue
                order.append(sku)

        summary = []
        for sku in order:
            total = revenues[sku].quantize(_CENT, rounding=ROUND_HALF_EVEN)
            if total == 0:
                total = Decimal("0.00")
            summary.append({
                "sku": sku,
                "quantity": quantities[sku],
                "revenue": str(total),
            })
    return summary
