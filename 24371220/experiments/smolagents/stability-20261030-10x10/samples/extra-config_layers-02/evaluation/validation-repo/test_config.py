import pytest
from merge import merge_layers
from settings import build_config


def test_nested_merge_and_independent_tree():
    first = {'network': {'timeout': 3, 'hosts': ['a']}}
    result = merge_layers(first, {'network': {'timeout': 5}})
    assert result == {'network': {'timeout': 5, 'hosts': ['a']}}
    result['network']['hosts'].append('b')
    assert first['network']['hosts'] == ['a']


def test_environment_is_last_layer():
    assert build_config({'network': {'timeout': 2}}, {},
                        {'APP_TIMEOUT': ' +12 ', 'APP_DEBUG': 'FALSE'}) == {
                            'network': {'timeout': 12}, 'debug': False}


@pytest.mark.parametrize('value', ['0', '-2', '1.2', 'no'])
def test_bad_timeout(value):
    with pytest.raises(ValueError):
        build_config({}, {}, {'APP_TIMEOUT': value})
