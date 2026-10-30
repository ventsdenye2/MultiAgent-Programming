import math


class TTLCache:
    def __init__(self, clock):
        self.clock = clock
        self._entries = {}
        self._running = {}

    @staticmethod
    def _validate_ttl(ttl):
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)):
            raise ValueError("ttl must be a finite nonnegative int or float")
        if isinstance(ttl, float) and not math.isfinite(ttl):
            raise ValueError("ttl must be finite")
        if ttl < 0:
            raise ValueError("ttl must be nonnegative")
        return ttl

    def get(self, key, loader, ttl):
        self._validate_ttl(ttl)

        if key in self._running:
            raise RuntimeError("recursive get for a key whose loader is running")

        if ttl > 0 and key in self._entries:
            value, expires_at = self._entries[key]
            if self.clock() < expires_at:
                return value

        load_state = {"cancelled": False}
        self._running[key] = load_state
        try:
            value = loader()

            if ttl > 0:
                expires_at = self.clock() + ttl
                if not load_state["cancelled"]:
                    self._entries[key] = (value, expires_at)

            return value
        finally:
            del self._running[key]

    def invalidate(self, key):
        self._entries.pop(key, None)
        load_state = self._running.get(key)
        if load_state is not None:
            load_state["cancelled"] = True

    def clear(self):
        self._entries.clear()
        for load_state in self._running.values():
            load_state["cancelled"] = True
