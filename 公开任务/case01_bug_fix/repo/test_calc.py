from calc import add_tax, apply_discount, split_bill, total


def test_apply_discount():
    assert apply_discount(200, 0.8) == 160


def test_apply_discount_full_price():
    assert apply_discount(99.9, 1.0) == 99.9


def test_add_tax():
    assert round(add_tax(100), 2) == 113.0


def test_total():
    assert round(total([100, 200]), 2) == 339.0


def test_split_bill():
    assert split_bill(100, 3) == 33.33
