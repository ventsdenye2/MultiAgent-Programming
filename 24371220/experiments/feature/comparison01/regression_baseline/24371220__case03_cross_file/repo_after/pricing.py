from models import Item, User


VIP_DISCOUNT = 0.9
FREE_SHIPPING_THRESHOLD = 200
SHIPPING_FEE = 10


def items_subtotal(items):
    """商品小计。"""
    return sum(item.price for item in items)


def apply_vip(subtotal, user):
    """VIP 用户全场九折，普通用户原价。"""
    if user.is_vip:
        return subtotal * VIP_DISCOUNT
    return subtotal


def shipping_fee(amount):
    """折后满 200 免运费，否则收 10 元。"""
    if amount >= FREE_SHIPPING_THRESHOLD:
        return 0
    return SHIPPING_FEE
