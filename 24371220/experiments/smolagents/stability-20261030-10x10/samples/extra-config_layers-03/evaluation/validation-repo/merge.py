def _clone(value):
    """Return a deep copy of dictionaries/lists; other values are atomic."""
    if isinstance(value, dict):
        return {key: _clone(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone(item) for item in value]
    return value


def _merge(base, override):
    result = {key: _clone(value) for key, value in base.items()}
    for key, value in override.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            result[key] = _merge(current, value)
        else:
            result[key] = _clone(value)
    return result


def merge_layers(*layers):
    """Merge dictionary layers from left to right.

    Later values win. Nested dictionaries are merged recursively; lists and
    every other value (including ``None``) replace the earlier value. The
    result is an independent tree that shares no mutable containers with the
    inputs, and the inputs are never modified.
    """
    result = {}
    for layer in layers:
        if not isinstance(layer, dict):
            raise TypeError("every layer must be a dictionary")
        result = _merge(result, layer)
    return result
