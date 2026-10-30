from merge import merge_layers


def _parse_timeout(raw):
    """Parse a positive base-10 ASCII integer, allowing whitespace and a leading +."""
    if not isinstance(raw, str):
        raise ValueError("APP_TIMEOUT must be a string containing a positive integer")

    text = raw.strip()
    if text.startswith("+"):
        text = text[1:]

    if not text or not all("0" <= character <= "9" for character in text):
        raise ValueError("APP_TIMEOUT must be a positive base-10 ASCII integer")

    value = int(text, 10)
    if value <= 0:
        raise ValueError("APP_TIMEOUT must be greater than zero")
    return value


def _parse_debug(raw):
    """Parse one of the accepted case-insensitive boolean spellings."""
    if not isinstance(raw, str):
        raise ValueError("APP_DEBUG must be true, false, 1, or 0")

    text = raw.strip().lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    raise ValueError("APP_DEBUG must be true, false, 1, or 0")


def build_config(defaults, overrides, environ):
    result = merge_layers(defaults, overrides)

    if "APP_TIMEOUT" in environ:
        timeout = _parse_timeout(environ["APP_TIMEOUT"])
        if "network" not in result:
            result["network"] = {}
        elif not isinstance(result["network"], dict):
            raise ValueError("network must be a dictionary when APP_TIMEOUT is supplied")
        result["network"]["timeout"] = timeout

    if "APP_DEBUG" in environ:
        result["debug"] = _parse_debug(environ["APP_DEBUG"])

    return result
