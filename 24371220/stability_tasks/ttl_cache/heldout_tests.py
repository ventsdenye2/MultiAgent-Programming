import pytest
from cache import TTLCache


def test_none_and_completion_time_and_hit_does_not_extend():
    now = [0]
    cache = TTLCache(lambda: now[0])
    calls = []
    def load():
        calls.append(1)
        now[0] = 10
        return None
    assert cache.get('x', load, 5) is None
    now[0] = 14
    assert cache.get('x', lambda: 9, 100) is None
    assert calls == [1]
    now[0] = 15
    assert cache.get('x', lambda: 7, 1) == 7


@pytest.mark.parametrize('ttl', [True, None, '3', float('inf'), float('nan'), -0.1])
def test_validation_precedes_hits_and_loads(ttl):
    cache = TTLCache(lambda: 0)
    cache.get('x', lambda: 1, 10)
    def forbidden():
        raise AssertionError('loader must not run')
    with pytest.raises(ValueError):
        cache.get('x', forbidden, ttl)


def test_loader_failure_is_not_cached_and_guard_recovers():
    cache = TTLCache(lambda: 0)
    def bad():
        raise LookupError('failure')
    with pytest.raises(LookupError):
        cache.get('x', bad, 2)
    assert cache.get('x', lambda: 8, 2) == 8


def test_zero_bypasses_existing_entry_without_replacing_it():
    cache = TTLCache(lambda: 0)
    assert cache.get('x', lambda: 1, 10) == 1
    assert cache.get('x', lambda: 2, 0) == 2
    assert cache.get('x', lambda: 3, 10) == 1


def test_clear_during_load_and_other_key_invalidation():
    cache = TTLCache(lambda: 0)
    def clear_load():
        cache.clear()
        return 1
    assert cache.get('x', clear_load, 10) == 1
    assert cache.get('x', lambda: 2, 10) == 2
    def other_load():
        cache.invalidate('other')
        return 3
    assert cache.get('y', other_load, 10) == 3
    assert cache.get('y', lambda: 4, 10) == 3
    assert cache.invalidate('missing') is None
    assert cache.clear() is None


def test_reentrant_same_key_after_invalidation_and_other_key_nesting():
    cache = TTLCache(lambda: 0)
    def recurse():
        cache.invalidate('x')
        return cache.get('x', lambda: 9, 1)
    with pytest.raises(RuntimeError):
        cache.get('x', recurse, 1)
    assert cache.get('x', lambda: cache.get('y', lambda: 2, 1) + 1, 1) == 3
