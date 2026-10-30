import copy
import pytest
from graph import build_order
from paths import canonical_path


@pytest.mark.parametrize('value', ['', '.', 'a/..', '/a', 'a/../../b', 'C:x', 'a\\b', 'a\x00b'])
def test_rejected_paths(value):
    with pytest.raises(ValueError):
        canonical_path(value)


def test_preserve_spaces_and_types():
    assert canonical_path(' a /./b ') == ' a /b '
    with pytest.raises(TypeError):
        canonical_path(None)
    with pytest.raises(TypeError):
        build_order({'a': 'b'})
    with pytest.raises(TypeError):
        build_order([])


def test_alias_union_duplicates_and_no_mutation():
    graph = {'./a': ['b', './b'], 'x/../a': ['c'], 'b': [], 'c': []}
    before = copy.deepcopy(graph)
    assert build_order(graph) == ['b', 'c', 'a']
    assert graph == before
    assert build_order({}) == []


def test_unknown_and_canonical_self_cycle():
    with pytest.raises(ValueError):
        build_order({'a': ['b']})
    with pytest.raises(ValueError):
        build_order({'a': ['./a']})


def test_newly_ready_node_competes_with_existing_ready_nodes():
    assert build_order({'z': [], 'a': ['b'], 'b': [], 'c': []}) == ['b', 'a', 'c', 'z']
