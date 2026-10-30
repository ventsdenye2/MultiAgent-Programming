def canonical_path(value):
    if not isinstance(value, str):
        raise TypeError("path must be a string")
    if not value:
        raise ValueError("path must not be empty")
    if value.startswith("/"):
        raise ValueError("path must be relative")
    if "\\" in value:
        raise ValueError("backslashes are not allowed")
    if ":" in value:
        raise ValueError("colons are not allowed")
    if "\x00" in value:
        raise ValueError("NUL characters are not allowed")

    components = []
    for component in value.split("/"):
        if component == "" or component == ".":
            continue
        if component == "..":
            if not components:
                raise ValueError("path escapes the root")
            components.pop()
        else:
            components.append(component)

    if not components:
        raise ValueError("path must not be empty")
    return "/".join(components)
