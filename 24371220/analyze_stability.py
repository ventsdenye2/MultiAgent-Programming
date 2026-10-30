"""Read-only per-request milestones for a recorded course cohort."""
import argparse
import json
from pathlib import Path

from inspect_evaluation import inspect_log


def milestones(path):
    request = 0
    writes, tests, finishes, errors, saved = [], [], [], [], []
    for line in path.read_text(encoding='utf-8').splitlines():
        event = json.loads(line)
        kind = event.get('event')
        if kind == 'model_request':
            request = event['number']
        marker = {'request': request, 'seq': event.get('seq')}
        if kind == 'file_write' and event.get('changed'):
            writes.append({**marker, 'path': event['path'], 'file_hash': event.get('file_hash')})
        elif kind == 'command_result' and event.get('argv', [])[1:] == ['-m', 'pytest', '-q']:
            tests.append({**marker, 'rc': event.get('rc'), 'timed_out': event.get('timed_out', False)})
        elif kind == 'finish' or (kind == 'agent_step' and event.get('step', {}).get('is_final_answer')):
            finishes.append(marker)
        elif kind in {'agent_error', 'tool_error', 'model_error'}:
            errors.append({**marker, 'event': kind, 'type': event.get('error_type'),
                           'tool': event.get('tool'), 'error': event.get('error')})
        elif kind == 'paper_answer':
            saved.append(marker)
    last_write = writes[-1] if writes else None
    return {'first_write': writes[0] if writes else None, 'last_write': last_write,
            'report_writes': [w for w in writes if w['path'] == 'report.json'],
            'writes': writes, 'tests': tests,
            'tests_after_last_write': [t for t in tests if last_write and t['seq'] > last_write['seq']],
            'finish': finishes, 'errors': errors, 'saved_answer_events': saved,
            'protocol_errors': sum(e['type'] == 'AgentParsingError' for e in errors),
            'tool_errors': sum(e['event'] == 'tool_error' for e in errors),
            'infrastructure_errors': sum(e['event'] == 'model_error' for e in errors)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('study', type=Path)
    args = parser.parse_args()
    rows = []
    for sample_path in sorted((args.study / 'samples').glob('*/sample.json')):
        sample = json.loads(sample_path.read_text(encoding='utf-8'))
        task = sample['task']
        if task not in {'source', 'paper'}:
            continue
        path = sample_path.parent / 'evaluation' / task / 'development/run.log'
        if not path.exists():
            rows.append({'sample': sample_path.parent.name, **sample})
            continue
        inspection = inspect_log(path)
        rows.append({'sample': sample_path.parent.name, **sample,
                     'milestones': milestones(path),
                     'paper_page_count': inspection['paper_page_count'],
                     'section_topics': inspection['section_topics']})
    out = args.study / 'MILESTONES.json'
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps([{k: row.get(k) for k in ('sample', 'passed', 'score', 'requests', 'milestones')}
                      for row in rows], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
