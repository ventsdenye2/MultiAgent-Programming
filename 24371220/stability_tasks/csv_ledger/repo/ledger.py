import csv
import io


def summarize(text):
    return [{'sku': row['sku'], 'quantity': int(row['quantity']),
             'revenue': str(float(row['unit_price']) * int(row['quantity']))}
            for row in csv.DictReader(io.StringIO(text))]
