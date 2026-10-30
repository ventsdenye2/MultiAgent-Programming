from copy import deepcopy


def merge_layers(*layers):
    result = {}
    for layer in layers:
        if not isinstance(layer, dict):
            raise TypeError('layers must be dictionaries')
        for key, value in layer.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = merge_layers(result[key], value)
            else:
                result[key] = deepcopy(value)
    return result
