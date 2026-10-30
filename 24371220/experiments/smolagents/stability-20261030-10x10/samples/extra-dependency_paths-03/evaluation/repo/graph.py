import heapq

from paths import canonical_path


def build_order(graph):
    """Return a deterministic dependency-first ordering of canonical nodes."""
    if not isinstance(graph, dict):
        raise TypeError("graph must be a dict")

    dependencies = {}
    for key, value in graph.items():
        if not isinstance(value, list):
            raise TypeError("each dependency collection must be a list")
        node = canonical_path(key)
        bucket = dependencies.setdefault(node, set())
        for dependency in value:
            bucket.add(canonical_path(dependency))

    for node, required in dependencies.items():
        for dependency in required:
            if dependency not in dependencies:
                raise ValueError(
                    "undeclared dependency: {0!r}".format(dependency)
                )

    dependents = {}
    for node in dependencies:
        dependents[node] = []
    indegree = {}
    for node, required in dependencies.items():
        indegree[node] = len(required)
        for dependency in required:
            dependents[dependency].append(node)

    ready = [node for node, count in indegree.items() if count == 0]
    heapq.heapify(ready)

    order = []
    while ready:
        node = heapq.heappop(ready)
        order.append(node)
        for dependent in dependents[node]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, dependent)

    if len(order) != len(dependencies):
        raise ValueError("cycle detected")

    return order
