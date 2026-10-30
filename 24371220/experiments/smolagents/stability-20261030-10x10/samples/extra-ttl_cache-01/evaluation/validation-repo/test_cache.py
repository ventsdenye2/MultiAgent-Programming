import pytest
from cache import TTLCache


def test_expiration_at_exact_deadline_and_invalidate():
    now = [0]
    cache = TTLCache(lambda: now[0])
    assert cache.get('x', lambda: 1, 5) == 1
    now[0] = 4
    assert cache.get('x', lambda: 2, 100) == 1
    now[0] = 5
    assert cache.get('x', lambda: 3, 5) == 3
    cache.invalidate('x')
    assert cache.get('x', lambda: 4, 5) == 4


def test_zero_ttl_and_invalid_ttl():
    cache = TTLCache(lambda: 0)
    assert cache.get('x', lambda: 1, 0) == 1
    assert cache.get('x', lambda: 2, 0) == 2
    with pytest.raises(ValueError):
        cache.get('x', lambda: 3, -1)


def test_invalidate_during_load():
    cache = TTLCache(lambda: 0)
    def load():
        cache.invalidate('x')
        return 1
    assert cache.get('x', load, 10) == 1
    assert cache.get('x', lambda: 2, 10) == 2
