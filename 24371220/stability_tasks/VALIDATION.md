# Offline validation evidence

Full-bank run: `validation-20261030-110226-974671/summary.json`.
After the cache reference's numeric validation was tightened to avoid converting
large integers to float, the final cache files were rechecked in
`validation-20261030-110427-056642/summary.json`.
Both summaries have `ok: true` and `provider_calls: 0`; raw logs and JUnit XML
are retained. The task inputs were fingerprinted before and after each run.

| Task | Visible tests | Visible + hidden | Initial visible failures | Initial combined failures | Reference failures |
|---|---:|---:|---:|---:|---:|
| config_layers | 6 | 17 | 6 | 15 | 0 |
| csv_ledger | 5 | 16 | 5 | 14 | 0 |
| unicode_words | 3 | 10 | 3 | 8 | 0 |
| dependency_paths | 3 | 15 | 3 | 15 | 0 |
| ttl_cache | 3 | 14 | 3 | 13 | 0 |

No test run had collection errors or skipped tests. This verifies the bank's
baselines and reference solutions only; it is not evidence of agent success.

Commands (project WSL Python 3.12 environment):

```bash
.venv/bin/python stability_tasks/validate_tasks.py
.venv/bin/python stability_tasks/validate_tasks.py --task ttl_cache
```
