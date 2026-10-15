"""真实对照实验，复用课程评测器；不改评测器和初始题目。"""
import hashlib
import json
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
course = root.parent
sys.path.insert(0, str(course / 'tools'))
from evaluator import evaluate

config = json.loads((root / 'config.json').read_text())
rules = json.loads((course / 'tools/public_rules.json').read_text())
output = root / 'experiments/feature/comparison01'
output.mkdir(parents=True, exist_ok=False)
snapshot = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.glob('*.py')}
(output / 'protocol.json').write_text(json.dumps({
    'config': config, 'source_sha256': snapshot, 'agent_timeout': 600,
    'pytest_timeout': 120, 'design': 'case05 off/on alternating 3 repetitions; all five once per mode',
    'changing_variable': 'MINI_CONTEXT_MODE'}, indent=2), encoding='utf-8')
rows = []
schedule = [(f'repeat{i}_{mode}', mode, ['case05_long_log'])
            for i in range(1, 4) for mode in ('baseline', 'diagnostic')]
schedule += [(f'regression_{mode}', mode, list(rules)) for mode in ('baseline', 'diagnostic')]
for name, mode, cases in schedule:
    out = output / name
    out.mkdir()
    os.environ['MINI_CONTEXT_MODE'] = mode
    (out / 'config.json').write_text(json.dumps({**config, 'context_mode': mode}, indent=2))
    for case in cases:
        print(name, case, flush=True)
        row = evaluate(root, course / '公开任务' / case, out, config['model'],
                       rules[case], key_env=config['key_env'])
        row.update(experiment=name, context_mode=mode)
        (out / f'{root.name}__{case}' / 'result.json').write_text(
            json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
        rows.append(row)
        (output / 'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        print(row['status'], row['prompt_tokens'], row['model_requests'], flush=True)
