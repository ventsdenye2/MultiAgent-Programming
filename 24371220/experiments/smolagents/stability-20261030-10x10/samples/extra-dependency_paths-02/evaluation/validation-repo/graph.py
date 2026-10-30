from paths import canonical_path


def build_order(graph):
    if not isinstance(graph, dict):
        raise TypeError("graph must be a dict")

    items = list(graph.items())
    for _, dependencies in items:
        if not isinstance(dependencies, list):
            raise TypeError("dependencies must be a list")

    dependency_map = {}
    for key, dependencies in items:
        node = canonical_path(key)
        merged = dependency_map.setdefault(node, set())
        for dependency in dependencies:
            merged.add(canonical_path(dependency))

    nodes = set(dependency_map)
    dependents = {node: [] for node in nodes}
    indegree = {}

    for node, dependencies in dependency_map.items():
        for dependency in dependencies:
            if dependency not in nodes:
                raise ValueError("dependency is not a declared node")
        indegree[node] = len(dependencies)
        for dependency in dependencies:
            dependents[dependency].append(node)

    ready = [node for node in nodes if indegree[node] == 0]
    order = []

    while ready:
        node = min(ready)
        ready.remove(node)
        order.append(node)
        for dependent in dependents[node]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)

    if len(order) != len(nodes):
        raise ValueError("graph contains a cycle")

    return order
