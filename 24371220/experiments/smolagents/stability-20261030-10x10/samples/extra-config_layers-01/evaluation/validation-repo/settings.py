"""Build application configuration from layers and environment keys."""

import re

from merge import merge_layers

__all__ = ["build_config"]

_TIMEOUT_RE = re.compile(r"[0-9]+")


def _parse_timeout(raw):
    if not isinstance(raw, str):
        raise ValueError("APP_TIMEOUT must be a string, got %r" % (raw,))
    text = raw.strip()
    if text.startswith("+"):
        text = text[1:]
    if not _TIMEOUT_RE.fullmatch(text):
        raise ValueError("APP_TIMEOUT must be a positive integer, got %r" % (raw,))
    value = int(text)
    if value <= 0:
        raise ValueError("APP_TIMEOUT must be a positive integer, got %r" % (raw,))
    return value


def _parse_debug(raw):
    if not isinstance(raw, str):
        raise ValueError("APP_DEBUG must be a string, got %r" % (raw,))
    text = raw.strip().lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    raise ValueError("APP_DEBUG must be a boolean value, got %r" % (raw,))


def build_config(defaults, overrides, environ):
    """Merge ``defaults`` and ``overrides``, then apply environment keys.

    Recognized environment keys are ``APP_TIMEOUT`` and ``APP_DEBUG``; all
    other keys are ignored. ``os.environ`` is never read.
    """
    result = merge_layers(defaults, overrides)

    if "APP_TIMEOUT" in environ:
        timeout = _parse_timeout(environ["APP_TIMEOUT"])
        if "network" not in result:
            result["network"] = {}
        elif not isinstance(result["network"], dict):
            raise ValueError("network setting must be a dict")
        result["network"]["timeout"] = timeout

    if "APP_DEBUG" in environ:
        result["debug"] = _parse_debug(environ["APP_DEBUG"])

    return result
