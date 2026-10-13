"""简单的价格计算模块。"""

TAX_RATE = 0.13


def add_tax(price):
    """含税价 = 价格 * (1 + 税率)。"""
    return price * (1 + TAX_RATE)


def apply_discount(price, discount):
    """打折：discount 为折扣率，如 0.8 表示八折。"""
    return price * discount / 100


def total(prices):
    """合计含税总价。"""
    return add_tax(sum(prices))


def split_bill(amount, n):
    """n 人 AA，每人应付（保留两位小数）。"""
    return round(amount / n, 2)
