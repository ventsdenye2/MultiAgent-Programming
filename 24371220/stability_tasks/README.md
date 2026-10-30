# Original Python stability tasks

These five tasks are independent of the official course tasks. Each task has a
`task.md`, an initial `repo/`, hidden tests outside that repo, and a `reference/`
tree containing only the allowed replacement files. No external service is used.

| ID | Topic | Allowed files |
|---|---|---|
| config_layers | Recursive merge and environment parsing | merge.py, settings.py |
| csv_ledger | CSV validation and exact decimal aggregation | ledger.py |
| unicode_words | Unicode categories and canonical word counts | words.py |
| dependency_paths | Canonical relative paths and deterministic graph order | paths.py, graph.py |
| ttl_cache | Expiration, reentrancy and invalidation during loading | cache.py |

`manifest.json` is the runner input. Copy **only** a task's `repo/` into the
agent's fresh working directory and pass `task.md` separately. Use generic
profile, the manifest's explicit editable list, and a 20-request cap. Never copy
this entire task bank, hidden tests, reference implementations, or offline
validation logs into an agent workspace or model context.

After the agent exits, create a separate isolated verification copy of its repo,
copy only `heldout_tests.py` into that copy as `test_heldout.py`, and run full
pytest there. Keep visible verification, hidden verification, agent exit status,
and process requirements as separate facts. Every task requires the agent to run
baseline/full final pytest and finish normally; external hidden tests cannot
replace the agent's final verification.

Run `python stability_tasks/validate_tasks.py` from the submission directory to
verify both initial and reference code against visible and hidden tests without
calling a model. Results and complete pytest output are saved under
`stability_tasks/validation-<timestamp>/`. Inputs are never modified.
