import pytest
from models import Item, User
from cart import checkout
from pricing import apply_vip, shipping_fee


@pytest.mark.parametrize("amount", [0, 10, 123.45, 500])
def test_vip_pricing_layer(amount):
    assert apply_vip(amount, User("vip", True)) == pytest.approx(amount * .9)
    assert apply_vip(amount, User("normal")) == amount


@pytest.mark.parametrize("amount,fee", [(0, 10), (199.99, 10), (200, 0), (200.01, 0)])
def test_shipping_boundary(amount, fee):
    assert shipping_fee(amount) == fee


def test_single_item_decimal_checkout():
    goods, fee, total = checkout(User("vip", True), [Item("one", 123.45)])
    assert goods == pytest.approx(111.105)
    assert fee == 10
    assert total == pytest.approx(121.105)
