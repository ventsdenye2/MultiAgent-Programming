def canonical_path(value):
    """Return the canonical form of a relative POSIX path string."""
    if not isinstance(value, str):
        raise TypeError("path must be a str")

    if value.startswith("/"):
        raise ValueError("path must be relative")

    if "\\" in value:
        raise ValueError("backslash is not allowed in a path")

    if ":" in value:
        raise ValueError("colon is not allowed in a path")

    if "\x00" in value:
        raise ValueError("NUL is not allowed in a path")

    parts = []
    for component in value.split("/"):
        if component == "" or component == ".":
            continue
        if component == "..":
            if not parts:
                raise ValueError("path escapes the root")
            parts.pop()
            continue
        parts.append(component)

    if not parts:
        raise ValueError("empty path")

    return "/".join(parts)
