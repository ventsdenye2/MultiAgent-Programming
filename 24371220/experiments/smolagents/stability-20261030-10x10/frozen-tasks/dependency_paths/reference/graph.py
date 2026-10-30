import heapq
from paths import canonical_path


def build_order(graph):
    if not isinstance(graph, dict):
        raise TypeError('graph must be dict')
    dependencies = {}
    for key, values in graph.items():
        if not isinstance(values, list):
            raise TypeError('dependencies must be lists')
        node = canonical_path(key)
        dependencies.setdefault(node, set()).update(canonical_path(value) for value in values)
    if any(dep not in dependencies for values in dependencies.values() for dep in values):
        raise ValueError('unknown dependency')
    reverse = {key: set() for key in dependencies}
    remaining = {key: len(values) for key, values in dependencies.items()}
    for node, values in dependencies.items():
        for dep in values:
            reverse[dep].add(node)
    ready = [key for key, count in remaining.items() if not count]
    heapq.heapify(ready)
    result = []
    while ready:
        node = heapq.heappop(ready)
        result.append(node)
        for dependent in reverse[node]:
            remaining[dependent] -= 1
            if not remaining[dependent]:
                heapq.heappush(ready, dependent)
    if len(result) != len(dependencies):
        raise ValueError('dependency cycle')
    return result
