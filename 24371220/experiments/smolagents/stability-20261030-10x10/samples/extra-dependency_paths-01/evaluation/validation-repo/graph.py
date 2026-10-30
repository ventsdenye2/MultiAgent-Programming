from paths import canonical_path


def build_order(graph):
    """Return a deterministic dependency order for *graph*.

    ``graph`` maps relative POSIX path strings to lists of dependency path
    strings.  Keys and dependencies are canonicalized; keys sharing one
    canonical form are merged.  Every dependency must be a declared canonical
    key.  The result lists each canonical node once, dependencies first,
    choosing the lexicographically smallest available node at each step.
    """
    if not isinstance(graph, dict):
        raise TypeError("graph must be a dict")

    dependencies_by_node = {}
    for key, dependencies in graph.items():
        if not isinstance(dependencies, list):
            raise TypeError("dependencies must be a list")
        node = canonical_path(key)
        bucket = dependencies_by_node.setdefault(node, set())
        for dependency in dependencies:
            bucket.add(canonical_path(dependency))

    for dependencies in dependencies_by_node.values():
        for dependency in dependencies:
            if dependency not in dependencies_by_node:
                raise ValueError("undeclared dependency: %s" % dependency)

    order = []
    done = set()
    remaining = set(dependencies_by_node)
    while remaining:
        available = [
            node for node in remaining
            if dependencies_by_node[node] <= done
        ]
        if not available:
            raise ValueError("cycle detected")
        next_node = min(available)
        order.append(next_node)
        done.add(next_node)
        remaining.remove(next_node)
    return order
