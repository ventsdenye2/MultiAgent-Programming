import re
from merge import merge_layers


def build_config(defaults, overrides, environ):
    result = merge_layers(defaults, overrides)
    if 'APP_TIMEOUT' in environ:
        text = environ['APP_TIMEOUT'].strip()
        if not re.fullmatch(r'\+?[0-9]+', text) or int(text) <= 0:
            raise ValueError('timeout must be a positive ASCII integer')
        network = result.setdefault('network', {})
        if not isinstance(network, dict):
            raise ValueError('network must be a dictionary')
        network['timeout'] = int(text)
    if 'APP_DEBUG' in environ:
        text = environ['APP_DEBUG'].strip().lower()
        if text not in {'true', 'false', '1', '0'}:
            raise ValueError('invalid debug flag')
        result['debug'] = text in {'true', '1'}
    return result
