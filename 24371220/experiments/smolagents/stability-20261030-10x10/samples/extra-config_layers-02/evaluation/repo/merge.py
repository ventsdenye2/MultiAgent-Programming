"""Layered dictionary merging."""


def _copy(value):
    """Deep-copy dictionaries and lists; other values are returned as-is."""
    if isinstance(value, dict):
        return {key: _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value


def _merge_into(target, layer):
    for key, value in layer.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            _merge_into(target[key], value)
        else:
            target[key] = _copy(value)


def merge_layers(*layers):
    """Merge dictionary layers left to right.

    Later values win; dictionaries are merged recursively, while lists and
    every other value (including ``None``) replace the earlier value.  The
    result is a fresh tree that shares no mutable dictionaries or lists with
    the inputs, and the inputs are never modified.
    """
    result = {}
    for layer in layers:
        if not isinstance(layer, dict):
            raise TypeError(
                "merge_layers() layers must be dicts, got %s" % type(layer).__name__
            )
        _merge_into(result, layer)
    return result
