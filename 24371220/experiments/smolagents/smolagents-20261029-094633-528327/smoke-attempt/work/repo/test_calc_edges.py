import pytest
from calc import add_tax, apply_discount, split_bill, total


@pytest.mark.parametrize("price,rate", [(0, .8), (200, 0), (80, .5), (12.5, .9), (200, 1)])
def test_discount_general(price, rate):
    assert apply_discount(price, rate) == pytest.approx(price * rate)


def test_existing_boundaries():
    assert total([]) == 0
    assert add_tax(0) == 0
    assert split_bill(12.5, 1) == 12.5
