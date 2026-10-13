from cart import checkout
from models import Item, User
from pricing import apply_vip, items_subtotal, shipping_fee


def make_items(*prices):
    return [Item(f"item{i}", p) for i, p in enumerate(prices)]


def test_vip_gets_discount():
    vip = User("alice", is_vip=True)
    goods, fee, total = checkout(vip, make_items(100, 100))
    assert goods == 180.0
    assert fee == 10
    assert total == 190.0


def test_normal_user_no_discount():
    bob = User("bob")
    goods, fee, total = checkout(bob, make_items(100, 100))
    assert goods == 200
    assert fee == 0
    assert total == 200


def test_vip_free_shipping_after_discount():
    vip = User("carol", is_vip=True)
    goods, fee, total = checkout(vip, make_items(150, 150))
    assert goods == 270.0
    assert fee == 0
    assert total == 270.0


def test_shipping_threshold_uses_discounted_amount():
    # 原价 210，VIP 折后 189，不满 200 应收运费
    vip = User("dave", is_vip=True)
    goods, fee, total = checkout(vip, make_items(210))
    assert goods == 189.0
    assert fee == 10
    assert total == 199.0


def test_subtotal_and_shipping_unchanged():
    assert items_subtotal(make_items(50, 60)) == 110
    assert shipping_fee(199) == 10
    assert shipping_fee(200) == 0
    assert apply_vip(100, User("eve")) == 100
