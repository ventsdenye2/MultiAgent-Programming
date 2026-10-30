import csv
import io
import re
from decimal import Decimal, InvalidOperation, localcontext, ROUND_HALF_EVEN


def summarize(text):
    try:
        rows = csv.reader(io.StringIO(text), strict=True)
        header = next(rows)
        header = [name.strip() for name in header]
        if len(header) != len(set(header)) or not {'sku', 'quantity', 'unit_price'} <= set(header):
            raise ValueError('invalid header')
        totals = {}
        with localcontext() as ctx:
            ctx.prec = 100
            for row in rows:
                if not row:
                    continue
                if len(row) != len(header):
                    raise ValueError('invalid cell count')
                data = dict(zip(header, row))
                sku, qty = data['sku'].strip(), data['quantity'].strip()
                if not sku or not re.fullmatch(r'[+-]?[0-9]+', qty):
                    raise ValueError('invalid sku or quantity')
                price = Decimal(data['unit_price'].strip())
                if not price.is_finite() or price < 0:
                    raise ValueError('invalid price')
                quantity = int(qty)
                previous_qty, previous_revenue = totals.get(sku, (0, Decimal(0)))
                totals[sku] = previous_qty + quantity, previous_revenue + quantity * price
            result = []
            for sku, (quantity, revenue) in totals.items():
                rounded = revenue.quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)
                if not rounded:
                    rounded = abs(rounded)
                result.append({'sku': sku, 'quantity': quantity, 'revenue': format(rounded, '.2f')})
            return result
    except (StopIteration, csv.Error, InvalidOperation) as exc:
        raise ValueError('invalid CSV ledger') from exc
