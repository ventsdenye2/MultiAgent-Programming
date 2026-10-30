import pytest
from merge import merge_layers
from settings import build_config


def test_scalars_none_and_list_replacement():
    assert merge_layers({'a': {'x': 1}}, {'a': None}, {'a': {'z': [2]}}) == {'a': {'z': [2]}}
    assert merge_layers({'a': [1]}, {'a': []}) == {'a': []}
    assert merge_layers() == {}


def test_later_tree_is_also_copied():
    second = {'x': [{'y': []}]}
    result = merge_layers({}, second)
    result['x'][0]['y'].append(1)
    assert second == {'x': [{'y': []}]}


@pytest.mark.parametrize('value', [[], None, 'x'])
def test_layer_type(value):
    with pytest.raises(TypeError):
        merge_layers(value)


@pytest.mark.parametrize('value', ['', '１２', '١', '+', '1_0'])
def test_timeout_ascii_only(value):
    with pytest.raises(ValueError):
        build_config({}, {}, {'APP_TIMEOUT': value})


def test_environment_validation_and_ignored_keys():
    assert build_config({'debug': 'keep'}, {}, {'OTHER': '1'}) == {'debug': 'keep'}
    assert build_config({}, {}, {'APP_DEBUG': ' 1 '}) == {'debug': True}
    assert build_config({}, {}, {'APP_TIMEOUT': '7'}) == {'network': {'timeout': 7}}
    with pytest.raises(ValueError):
        build_config({'network': []}, {}, {'APP_TIMEOUT': '7'})
    with pytest.raises(ValueError):
        build_config({}, {}, {'APP_DEBUG': 'yes'})
