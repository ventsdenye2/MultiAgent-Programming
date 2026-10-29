"""Read-only progress and usage reconciliation for one evaluation directory."""
import argparse
from collections import Counter
import json
from pathlib import Path


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def inspect_log(path, actions=0):
    events, invalid = [], 0
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            invalid += 1
    requests = [e for e in events if e.get('event') == 'model_request']
    responses = [e for e in events if e.get('event') == 'model_response']
    errors = [e for e in events if e.get('event') == 'model_error']
    usages = [(e.get('response') or {}).get('usage') or {} for e in responses]
    complete = bool(requests) and len(requests) == len(responses) and not invalid and all(
        all(type(u.get(k)) is int and u[k] >= 0 for k in ('prompt_tokens', 'completion_tokens', 'total_tokens'))
        and u['total_tokens'] == u['prompt_tokens'] + u['completion_tokens'] for u in usages)
    counts = Counter(e.get('event') for e in events)
    checks = [dict(argv=e.get('argv'), rc=e.get('rc'), timed_out=e.get('timed_out', False))
              for e in events if e.get('event') == 'command_result']
    tools = [e for e in events if e.get('event') in {'tool_call', 'tool_error', 'agent_error'}]
    evidence = {e['id']: e for e in events if e.get('event') == 'evidence'}
    presented = set().union(*(set(e.get('fully_exposed_ids', e.get('evidence_ids', [])))
                              for e in events if e.get('event') == 'context_exposure'))
    pages = sorted({evidence[eid]['page'] for eid in presented
                    if eid in evidence and evidence[eid].get('page') is not None})
    section_notes = [e for e in events if e.get('event') == 'section_note']
    result = {
        'path': str(path), 'requests': len(requests), 'responses': len(responses),
        'model_errors': len(errors), 'usage_complete': complete,
        'known_prompt_tokens': sum(u.get('prompt_tokens', 0) for u in usages),
        'known_completion_tokens': sum(u.get('completion_tokens', 0) for u in usages),
        'known_total_tokens': sum(u.get('total_tokens', 0) for u in usages),
        'cache_hit_tokens': sum(u.get('prompt_cache_hit_tokens', 0) for u in usages),
        'cache_miss_tokens': sum(u.get('prompt_cache_miss_tokens', 0) for u in usages),
        'max_request_chars': max((len(json.dumps(e['body'], ensure_ascii=False, separators=(',', ':')))
                                  for e in requests), default=0),
        'response_classes': dict(Counter(e.get('classification', 'unknown') for e in responses)),
        'last_request_parameters': {key: requests[-1]['body'].get(key)
                                    for key in ('model', 'max_tokens', 'thinking', 'reasoning_effort')}
                                   if requests else {},
        'counts': dict(counts), 'commands': checks,
        'paper_pages_exposed': pages, 'paper_page_count': len(pages),
        'section_note_count': len(section_notes),
        'section_topics': sorted({e['section'] for e in section_notes}),
        'changed_files': sorted({e['path'] for e in events if e.get('event') == 'file_write' and e.get('changed')}),
        'agent_error_types': dict(Counter(e.get('error_type') for e in events if e.get('event') == 'agent_error')),
        'recent_actions': [{'event': e['event'], 'tool': e.get('tool'),
                            'error_type': e.get('error_type'), 'error': e.get('error')}
                           for e in tools[-6:]],
        'result': read_json(path.with_name('run-result.json')),
        'invalid_lines': invalid,
    }
    if actions:
        result['model_actions'] = [{'request': e.get('number'),
            'content': (e.get('response', {}).get('choices') or [{}])[0].get('message', {}).get('content')}
            for e in responses[-actions:]]
        result['delivery'] = [e for e in events if e.get('event') == 'context_selection'][-actions:]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--save', type=Path)
    parser.add_argument('--actions', type=int, default=0, help='Include the last N actual model actions and delivery manifests')
    args = parser.parse_args()
    protocol = read_json(args.directory / 'protocol.json') or {}
    logs = [inspect_log(path, max(0, args.actions)) for path in sorted(args.directory.rglob('run.log'))
            if not any(part in {'workspace', 'submission', 'repo_after'} for part in path.relative_to(args.directory).parts)]
    report = {'stage': protocol.get('stage'), 'protocol_status': protocol.get('status'),
              'stage_results': protocol.get('results'), 'runs': logs,
              'total_requests': sum(r['requests'] for r in logs),
              'known_prompt_tokens': sum(r['known_prompt_tokens'] for r in logs),
              'known_completion_tokens': sum(r['known_completion_tokens'] for r in logs),
              'known_total_tokens': sum(r['known_total_tokens'] for r in logs),
              'usage_complete': bool(logs) and all(r['usage_complete'] for r in logs)}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.save:
        args.save.write_text(text + '\n', encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
