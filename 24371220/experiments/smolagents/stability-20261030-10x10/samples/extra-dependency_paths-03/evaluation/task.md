# Canonical dependency paths and deterministic build order

Only modify `paths.py` and `graph.py`. Standard library Python only.

`paths.canonical_path(value)` accepts a str describing a relative POSIX path.
Collapse empty components, '.' and internal '..'; reject any '..' that would
escape the root. Reject empty final path, leading '/', any backslash, any colon
and any NUL. Non-str raises TypeError; other invalid input raises ValueError.
Do not access the filesystem. Leading/trailing spaces are ordinary path content
and must be preserved. Example a//b/../c -> a/c, ../a invalid, a/.. invalid.

`graph.build_order(graph)` accepts a dict mapping path strings to lists of their
dependency path strings. Canonicalize every key/dependency. Multiple keys that
canonicalize to one node merge their dependency sets; duplicate dependencies
are ignored. Every dependency must be a declared canonical key, otherwise raise
ValueError. Return each canonical node exactly once, with all dependencies
before it. At each step choose the lexicographically smallest currently available
node (Python str order). A cycle, including a self edge after normalization,
raises ValueError. Empty graph -> []. Validate input type: graph must be dict
and each dependency collection must be list; otherwise TypeError. Preserve inputs.

Create a plan, fully read both editable files, and run `python -m pytest -q`
before any write. After the final edit run full `python -m pytest -q`, then mark
the plan done and final_answer normally on success. Never modify test files.
