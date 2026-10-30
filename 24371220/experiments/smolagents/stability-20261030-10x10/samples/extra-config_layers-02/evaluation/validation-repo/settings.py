"""Build application configuration from defaults, overrides and environ."""

import re

from merge import merge_layers

_TIMEOUT_RE = re.compile(r"\+?[0-9]+")

_TRUE_VALUES = frozenset({"true", "1"})
_FALSE_VALUES = frozenset({"false", "0"})


def _parse_timeout(raw):
    """Return a positive int from a decimal ASCII string, else ValueError."""
    if not isinstance(raw, str):
        raise ValueError("APP_TIMEOUT must be a string, got %r" % (raw,))
    text = raw.strip()
    if _TIMEOUT_RE.fullmatch(text) is None:
        raise ValueError("APP_TIMEOUT is not a decimal integer: %r" % (raw,))
    value = int(text, 10)
    if value <= 0:
        raise ValueError("APP_TIMEOUT must be positive, got %r" % (raw,))
    return value


def _parse_bool(raw):
    """Return a bool from true/false/1/0 (case-insensitive), else ValueError."""
    if not isinstance(raw, str):
        raise ValueError("APP_DEBUG must be a string, got %r" % (raw,))
    text = raw.strip().lower()
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    raise ValueError("APP_DEBUG must be true/false/1/0, got %r" % (raw,))


def build_config(defaults, overrides, environ):
    """Merge ``defaults`` and ``overrides``, then apply environment keys."""
    result = merge_layers(defaults, overrides)

    timeout = None
    if "APP_TIMEOUT" in environ:
        timeout = _parse_timeout(environ["APP_TIMEOUT"])

    debug = None
    if "APP_DEBUG" in environ:
        debug = _parse_bool(environ["APP_DEBUG"])

    if timeout is not None:
        if "network" not in result:
            result["network"] = {}
        network = result["network"]
        if not isinstance(network, dict):
            raise ValueError(
                "cannot apply APP_TIMEOUT: network is not a dictionary"
            )
        network["timeout"] = timeout

    if debug is not None:
        result["debug"] = debug

    return result
