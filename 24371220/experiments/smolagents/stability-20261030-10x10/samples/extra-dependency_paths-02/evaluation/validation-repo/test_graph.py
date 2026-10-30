import pytest
from graph import build_order
from paths import canonical_path


def test_canonical_and_escape():
    assert canonical_path('a//b/../c') == 'a/c'
    with pytest.raises(ValueError):
        canonical_path('../secret')


def test_topological_order_uses_ready_priority():
    assert build_order({'a': ['z'], 'b': [], 'z': []}) == ['b', 'z', 'a']


def test_cycle():
    with pytest.raises(ValueError):
        build_order({'a': ['b'], 'b': ['a']})
