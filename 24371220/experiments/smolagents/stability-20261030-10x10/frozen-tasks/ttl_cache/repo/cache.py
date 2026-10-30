class TTLCache:
    def __init__(self, clock):
        self.clock = clock
        self.values = {}

    def get(self, key, loader, ttl):
        if key not in self.values:
            self.values[key] = loader()
        return self.values[key]

    def invalidate(self, key):
        pass

    def clear(self):
        self.values.clear()
