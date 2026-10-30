"""Recursive merging of layered configuration dictionaries."""

__all__ = ["merge_layers"]


def _copy(value):
    """Return a deep copy of a configuration value.

    Dictionaries and lists are the only mutable containers in a
    configuration tree, so copying those two types keeps the merged result
    fully independent from the input layers.
    """
    if isinstance(value, dict):
        return {key: _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value


def _merge_into(target, source):
    for key, value in source.items():
        existing = target.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            _merge_into(existing, value)
        else:
            target[key] = _copy(value)


def merge_layers(*layers):
    """Merge dictionary layers, with later layers taking precedence.

    Dictionaries are merged recursively. Lists and every other value
    (including ``None``) replace the earlier value. Every layer must be a
    dictionary, otherwise ``TypeError`` is raised.
    """
    result = {}
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict):
            raise TypeError(
                "layer %d must be a dict, not %s"
                % (index, type(layer).__name__)
            )
        _merge_into(result, layer)
    return result
