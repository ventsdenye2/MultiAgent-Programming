import math


class TTLCache:
    def __init__(self, clock):
        self.clock = clock
        self.values = {}
        self.generations = {}
        self.epoch = 0
        self.running = set()

    def get(self, key, loader, ttl):
        if (isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl < 0
                or (isinstance(ttl, float) and not math.isfinite(ttl))):
            raise ValueError('ttl must be finite and nonnegative')
        if key in self.running:
            raise RuntimeError('recursive load for the same key')
        if ttl > 0 and key in self.values:
            value, deadline = self.values[key]
            if self.clock() < deadline:
                return value
            del self.values[key]
        token = self.epoch, self.generations.get(key, 0)
        self.running.add(key)
        try:
            value = loader()
            if ttl > 0 and token == (self.epoch, self.generations.get(key, 0)):
                self.values[key] = value, self.clock() + ttl
            return value
        finally:
            self.running.remove(key)

    def invalidate(self, key):
        self.values.pop(key, None)
        self.generations[key] = self.generations.get(key, 0) + 1

    def clear(self):
        self.values.clear()
        self.epoch += 1
