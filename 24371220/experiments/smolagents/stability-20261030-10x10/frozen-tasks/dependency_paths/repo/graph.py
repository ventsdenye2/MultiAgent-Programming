from paths import canonical_path


def build_order(graph):
    return sorted(canonical_path(key) for key in graph)
