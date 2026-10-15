from pricing import apply_vip, items_subtotal, shipping_fee


def checkout(user, items):
    """结算：返回 (商品金额, 运费, 应付总额)。"""
    subtotal = items_subtotal(items)
    after_discount = apply_vip(subtotal, user)
    fee = shipping_fee(after_discount)
    return after_discount, fee, after_discount + fee
