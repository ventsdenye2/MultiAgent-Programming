"""Read-only compact progress for the frozen context comparison, including native runs."""
import json
from pathlib import Path

from inspect_evaluation import inspect_log


def main():
    study = Path(__file__).parent / 'experiments/smolagents/context-20261105-p0-a-3x3'
    manifest = json.loads((study / 'comparison.json').read_text(encoding='utf-8'))
    rows = []
    for spec in manifest['schedule']:
        path = study / spec['arm'] / 'samples' / f"{spec['task']}-{spec['number']:02d}" / 'sample.json'
        if not path.exists():
            continue
        row = json.loads(path.read_text(encoding='utf-8'))
        item = {k: row.get(k) for k in ('arm', 'task', 'number', 'status', 'passed', 'score', 'requests')}
        if row['status'] == 'running':
            native = Path(row['native']) / 'results'
            protocol = native / 'protocol.json'
            if protocol.exists():
                item['stage'] = json.loads(protocol.read_text(encoding='utf-8')).get('status')
            log = native / row['task'] / 'development/run.log'
            if log.exists():
                report = inspect_log(log)
                item.update({k: report.get(k) for k in ('requests', 'responses', 'agent_error_types',
                    'paper_page_count', 'section_topics', 'changed_files', 'max_request_chars', 'result')})
        rows.append(item)
    print(json.dumps({'finished': sum(r['status'] != 'running' for r in rows), 'scheduled': len(manifest['schedule']), 'samples': rows}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
