def canonical_path(value):
    r"""Return the canonical form of a relative POSIX path string.

    Raises TypeError for non-str input and ValueError for every other
    invalid input.  Never touches the filesystem.
    """
    if not isinstance(value, str):
        raise TypeError("path must be a str")

    if not value:
        raise ValueError("empty path")
    if value[0] == "/":
        raise ValueError("absolute path not allowed")
    if "\\" in value:
        raise ValueError("backslash not allowed")
    if ":" in value:
        raise ValueError("colon not allowed")
    if "\x00" in value:
        raise ValueError("NUL not allowed")

    parts = []
    for part in value.split("/"):
        if part == "" or part == ".":
            continue
        if part == "..":
            if not parts:
                raise ValueError("path escapes the root")
            parts.pop()
            continue
        parts.append(part)

    if not parts:
        raise ValueError("empty path")
    return "/".join(parts)
