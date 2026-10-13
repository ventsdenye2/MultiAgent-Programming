class User:
    def __init__(self, name, is_vip=False):
        self.name = name
        self.is_vip = is_vip


class Item:
    def __init__(self, name, price):
        self.name = name
        self.price = price
