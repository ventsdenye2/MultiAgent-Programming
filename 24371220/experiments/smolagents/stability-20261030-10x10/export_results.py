"""Export completed samples for independent analysis; does not invoke the Agent."""
import csv
import json
from pathlib import Path


def export(study):
    rows = []
    for path in sorted((study / 'samples').glob('*/sample.json')):
        sample = json.loads(path.read_text(encoding='utf-8'))
        if sample['status'] == 'running':
            continue
        row = {'sample': path.parent.name}
        for key in ('task', 'number', 'status', 'passed', 'score', 'max_score',
                    'requests', 'prompt_tokens', 'completion_tokens', 'usage_complete',
                    'max_request_chars', 'agent_status', 'exit_code', 'failure_reason'):
            row[key] = sample.get(key)
        row['failed_checks'] = json.dumps({k: v for k, v in (sample.get('checks') or {}).items()
                                          if v is not True}, ensure_ascii=False)
        row['agent_errors'] = json.dumps(sample.get('agent_errors', {}), ensure_ascii=False)
        row['grading_tests'] = json.dumps(sample.get('tests', {}), ensure_ascii=False)
        row['sample_file'] = path.relative_to(study).as_posix()
        task = sample['task']
        log = path.parent / 'evaluation' / task / 'development/run.log'
        if not log.exists():
            log = path.parent / 'evaluation/run/run.log'
        if log.exists():
            events = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
            requests = [e for e in events if e.get('event') == 'model_request']
            responses = [e for e in events if e.get('event') == 'model_response']
            row['responses'] = len(responses)
            row['missing_response_requests'] = json.dumps(sorted(
                {e['number'] for e in requests} - {e['number'] for e in responses}))
            row['model_errors'] = json.dumps([{k: e.get(k) for k in
                ('number', 'classification', 'error_type', 'seq')} for e in events
                if e.get('event') == 'model_error'], ensure_ascii=False)
            row['log_file'] = log.relative_to(study).as_posix()
            starts = [e['time'] for e in events if e.get('event') == 'run_start']
            ends = [e['time'] for e in events if e.get('event') == 'run_result']
            row['agent_seconds'] = round(ends[-1] - starts[0], 2) if starts and ends else None
        rows.append(row)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (study / 'RESULTS.csv').open('w', encoding='utf-8-sig', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (study / 'RESULTS.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'completed_samples': len(rows), 'passed': sum(r['passed'] for r in rows),
                      'task_failures': sum(r['status'] == 'failed' for r in rows),
                      'infrastructure_failures': sum(r['status'] == 'infrastructure_failure' for r in rows)}, indent=2))


if __name__ == '__main__':
    export(Path(__file__).resolve().parent)
