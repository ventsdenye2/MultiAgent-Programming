# Deterministic TTL cache with safe invalidation

Only modify `cache.py`. Implement `TTLCache(clock)` with methods
`get(key, loader, ttl)`, `invalidate(key)`, and `clear()`. clock is an injected
zero-argument monotonic seconds function; never sleep or use wall-clock time.
Keys are hashable and loader is a zero-argument callable.

ttl must be a finite nonnegative int/float, excluding bool; invalid ttl raises
ValueError before looking at a cache hit or calling loader. A cached value is
usable only when clock() < its expiration; equality is expired. Cache hits do
not extend expiration or adopt a new ttl. A successful fresh load with ttl > 0
expires at clock() measured after loader returns, plus ttl. ttl=0 bypasses any
existing cache entry, loads each time, and does not store the fresh result or
remove a preexisting entry. Cached None is a legitimate hit for positive ttl.

invalidate(key) removes that key; clear() removes all keys; both return None.
If a loader calls invalidate for its own key, or calls clear, return its loaded
value to the current caller but do not cache that load. Invalidating a different
key does not cancel the current load. A loader exception propagates and is never
cached. Calling get recursively for the same key while that key's loader is
running raises RuntimeError, even after invalidate/clear. Other-key nesting is
allowed. Always clean up the running-key guard on success or failure. Single
thread only; no concurrency support required. Inputs are not mutated.

Create a plan, fully read cache.py, run `python -m pytest -q` before writing;
after the last write run the full same command, then complete the plan and
final_answer normally when successful. Standard library only; never edit tests.
