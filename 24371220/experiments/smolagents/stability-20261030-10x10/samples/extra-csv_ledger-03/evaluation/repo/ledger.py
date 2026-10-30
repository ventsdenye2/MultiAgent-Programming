import csv
import io
import re
from decimal import Decimal, InvalidOperation

_REQUIRED = ("sku", "quantity", "unit_price")
_INT_RE = re.compile(r"[+-]?[0-9]+")


def _format_cents(cents):
    if cents == 0:
        return "0.00"
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def _revenue_string(coefficient, exponent):
    # The exact revenue is coefficient * 10**exponent.  Round once to cents.
    if exponent >= -2:
        cents = coefficient * (10 ** (exponent + 2))
    else:
        shift = -2 - exponent
        divisor = 10 ** shift
        quotient, remainder = divmod(abs(coefficient), divisor)
        half = divisor // 2
        if remainder > half or (remainder == half and quotient % 2 == 1):
            quotient += 1
        cents = -quotient if coefficient < 0 else quotient
    return _format_cents(cents)


def summarize(text):
    if not isinstance(text, str) or text == "":
        raise ValueError("input is empty")

    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        rows = [row for row in reader if row]
    except (csv.Error, TypeError) as exc:
        raise ValueError("invalid CSV") from exc

    if not rows:
        raise ValueError("missing header")

    header = [name.strip() for name in rows[0]]
    seen = set()
    for name in header:
        if name in seen:
            raise ValueError("duplicate header")
        seen.add(name)

    if any(name not in seen for name in _REQUIRED):
        raise ValueError("missing required header")

    indexes = {name: index for index, name in enumerate(header)}
    sku_index = indexes["sku"]
    quantity_index = indexes["quantity"]
    price_index = indexes["unit_price"]

    aggregates = {}
    for row in rows[1:]:
        if len(row) != len(header):
            raise ValueError("row does not match header")

        sku = row[sku_index].strip()
        if not sku:
            raise ValueError("empty sku")

        quantity_text = row[quantity_index].strip()
        if _INT_RE.fullmatch(quantity_text) is None:
            raise ValueError("invalid quantity")
        quantity = int(quantity_text)

        price_text = row[price_index].strip()
        try:
            price = Decimal(price_text)
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("invalid price") from exc
        if not price.is_finite() or price < 0:
            raise ValueError("invalid price")

        sign, digits, exponent = price.as_tuple()
        coefficient = 0
        for digit in digits:
            coefficient = coefficient * 10 + digit
        if sign:
            coefficient = -coefficient

        term = quantity * coefficient
        previous = aggregates.get(sku)
        if previous is None:
            aggregates[sku] = [quantity, term, exponent]
        else:
            total_quantity, total_coefficient, total_exponent = previous
            if exponent < total_exponent:
                total_coefficient = (
                    total_coefficient * (10 ** (total_exponent - exponent)) + term
                )
                total_exponent = exponent
            elif exponent > total_exponent:
                total_coefficient += term * (10 ** (exponent - total_exponent))
            else:
                total_coefficient += term
            previous[0] = total_quantity + quantity
            previous[1] = total_coefficient
            previous[2] = total_exponent

    result = []
    for sku, (quantity, coefficient, exponent) in aggregates.items():
        result.append({
            "sku": sku,
            "quantity": quantity,
            "revenue": _revenue_string(coefficient, exponent),
        })
    return result
