# Fixed-version stability study

Baseline: `dbc405bda6f454a90f5c35392d00274834c80e31`; context_mode=evidence.

| Task | Passed / finished | Success rate | Wilson 95% interval |
|---|---:|---:|---:|
| config_layers | 3/3 | 100.0% | 43.9%–100.0% |
| csv_ledger | 3/3 | 100.0% | 43.9%–100.0% |
| dependency_paths | 3/3 | 100.0% | 43.9%–100.0% |
| paper | 1/10 | 10.0% | 1.8%–40.4% |
| source | 1/10 | 10.0% | 1.8%–40.4% |
| ttl_cache | 3/3 | 100.0% | 43.9%–100.0% |
| unicode_words | 3/3 | 100.0% | 43.9%–100.0% |

Actual requests: 739; known input/output tokens: 5586216/700074; usage complete: False.

All scheduled attempts count, including failures. No replacement samples or within-cohort code fixes.
Intervals quantify sampling uncertainty for these tasks; this is not a guarantee on arbitrary tasks.
