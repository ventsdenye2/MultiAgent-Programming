"""Validate a generated comparison snapshot and print compact observed facts."""
import hashlib
import json
from pathlib import Path
import sys

study = Path(__file__).parent / 'experiments/smolagents/context-20261105-p0-a-3x3'
data = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
assert data['configuration']['only_static_context_compact_differs']
rows = []
for arm, group in data['groups'].items():
    manifest = json.loads((study / arm / 'study.json').read_text(encoding='utf-8'))
    for name, digest in manifest['runtime_sha256'].items():
        assert hashlib.sha256((study / arm / 'frozen-agent' / name).read_bytes()).hexdigest() == digest
    for sample in group['samples']:
        log = sample.get('log')
        if not log:
            continue
        assert not log.get('inspection_error') and not log.get('milestones_error')
        assert log['usage']['complete']
        assert all(r['context_reconciles'] and r['context_accounting_count'] == 1 for r in log['requests'])
        rows.append({'arm': arm, 'sample': sample['sample'], 'usage': log['usage'],
                     'initial_context': log['requests'][0]['context'],
                     'mean_context': {k: v['mean'] for k, v in log['context_aggregate'].items()},
                     'positions': log['positions']})
assert sum(g['requests'] for g in data['groups'].values()) == 79
assert data['groups']['baseline']['tasks']['paper']['finished'] == 0
assert data['groups']['baseline']['tasks']['paper']['paused'] == 1
print(json.dumps({'tokens': data['known_tokens'], 'samples': rows,
                  'validation': 'Frozen runtime hashes, 79 accounting reconciliations, complete usage, paused denominator verified.'}, ensure_ascii=False, indent=2))
