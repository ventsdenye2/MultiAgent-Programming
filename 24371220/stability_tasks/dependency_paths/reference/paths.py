def canonical_path(value):
    if not isinstance(value, str):
        raise TypeError('path must be str')
    if value.startswith('/') or any(char in value for char in ('\\', ':', '\x00')):
        raise ValueError('invalid relative path')
    components = []
    for component in value.split('/'):
        if component in {'', '.'}:
            continue
        if component == '..':
            if not components:
                raise ValueError('path escapes root')
            components.pop()
        else:
            components.append(component)
    if not components:
        raise ValueError('empty path')
    return '/'.join(components)
