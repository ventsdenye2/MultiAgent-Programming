"""Read recorded baseline/static artifacts only; never run or resume evaluation.

Usage: python summarize_context_comparison.py [study] [--output-dir DIRECTORY]
Writes new CONTEXT-COMPARISON.json and REPORT.md; refuses to overwrite files.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from analyze_stability import milestones
from inspect_evaluation import inspect_log


CATEGORIES = ('core', 'tool', 'task', 'status', 'plan', 'recent', 'notes', 'evidence', 'other')
METRICS = (*CATEGORIES, 'json_wrapper_chars', 'compact_json_chars')
TOKENS = ('prompt_tokens', 'completion_tokens', 'total_tokens')
TOKEN_FIELDS = (*TOKENS, 'prompt_cache_hit_tokens', 'prompt_cache_miss_tokens')
DEFAULT_STUDY = Path(__file__).parent / 'experiments/smolagents/context-20261105-p0-a-3x3'
PAUSED_STATUSES = {'user_paused_before_request'}


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def number(value):
    return type(value) is int and value >= 0


class LogSnapshot:
    """Give both existing analyzers the same valid-line snapshot, even mid-write."""
    def __init__(self, path, events):
        self.path = path
        self.text = '\n'.join(json.dumps(e, ensure_ascii=False) for e in events)

    def read_text(self, **kwargs):
        return self.text

    def with_name(self, name):
        return self.path.with_name(name)

    def __str__(self):
        return str(self.path)


def aggregate_context(rows):
    result = {}
    for key in METRICS:
        values = [r.get(key) for r in rows if number(r.get(key))]
        result[key] = {'known_sum': sum(values), 'known_count': len(values),
                       'missing_count': len(rows) - len(values),
                       'mean': sum(values) / len(values) if values else None,
                       'max': max(values) if values else None}
    return result


def analyze_log(path):
    text = path.read_text(encoding='utf-8')
    events, invalid = [], []
    for index, line in enumerate(text.splitlines(), 1):
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError('not an object')
            events.append(event)
        except ValueError:
            invalid.append(index)
    snapshot = LogSnapshot(path, events)
    result = {'path': str(path), 'invalid_line_numbers': invalid,
              'snapshot_ends_with_newline': not text or text.endswith('\n')}
    # Existing analyzers are read-only. Retain diagnostics if a partial record
    # has unexpected fields rather than preventing the remaining cohort report.
    for name, function in (('inspection', inspect_log), ('milestones', milestones)):
        try:
            result[name] = function(snapshot)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            result[name + '_error'] = type(exc).__name__ + ': ' + str(exc)
    request_events = [e for e in events if e.get('event') == 'model_request']
    responses = {}
    accounting = {}
    for event in events:
        if event.get('event') == 'model_response':
            responses.setdefault(event.get('number'), []).append(event)
        if event.get('event') == 'context_accounting':
            accounting.setdefault(event.get('number'), []).append(event)
    requests = []
    for event in request_events:
        request = event.get('number')
        response_events = responses.get(request, [])
        response = response_events[-1] if response_events else {}
        usage = (response.get('response') or {}).get('usage') or {}
        usage = usage if isinstance(usage, dict) else {}
        missing = [k for k in TOKENS if not number(usage.get(k))]
        valid = not missing and usage['total_tokens'] == usage['prompt_tokens'] + usage['completion_tokens']
        accounts = accounting.get(request, [])
        account = accounts[-1] if accounts else {}
        serialized = account.get('text_json_chars') or {}
        raw = account.get('text_chars') or {}
        context = {key: serialized.get(key) for key in CATEGORIES}
        context.update({key: account.get(key) for key in METRICS if key not in CATEGORIES})
        start, end = event.get('time'), response.get('time')
        latency = end - start if type(start) in (int, float) and type(end) in (int, float) else None
        requests.append({'request': request, 'seq': event.get('seq'),
                         'request_time_unix': start, 'response_time_unix': end,
                         'response_latency_seconds': latency,
                         'response_count': len(response_events),
                         'usage': usage, 'usage_missing_fields': missing,
                         'usage_complete': valid,
                         'context_accounting_count': len(accounts),
                         'context': context, 'text_chars': raw,
                         'accounting_basis': account.get('basis'),
                         'context_reconciles': (sum(context[k] for k in CATEGORIES) +
                             context['json_wrapper_chars'] == context['compact_json_chars'])
                             if all(number(context[k]) for k in METRICS) else None})
    result['requests'] = requests
    result['usage'] = {f'known_{key}': sum(r['usage'].get(key, 0) for r in requests
                                         if number(r['usage'].get(key))) for key in TOKEN_FIELDS}
    result['usage'].update(requests=len(requests),
        requests_with_complete_usage=sum(r['usage_complete'] for r in requests),
        missing_or_invalid_usage_requests=[r['request'] for r in requests if not r['usage_complete']],
        complete=bool(requests) and all(r['usage_complete'] for r in requests) and not invalid)
    result['context_aggregate'] = aggregate_context([r['context'] for r in requests])
    result['orphan_response_numbers'] = [n for n in responses if n not in {r['request'] for r in requests}]
    result['orphan_accounting_numbers'] = [n for n in accounting if n not in {r['request'] for r in requests}]
    points = result.get('milestones', {})
    result['positions'] = {key: points.get(key) for key in ('first_write', 'last_write')}
    result['positions'].update(last_test=(points.get('tests') or [None])[-1],
        last_test_after_last_write=([t for t in points.get('tests_after_last_write', [])
                                    if not t.get('timed_out') and type(t.get('rc')) is int] or [None])[-1],
        finish=points.get('finish', []), last_request=requests[-1]['request'] if requests else None)
    return result


def summarize(study):
    comparison = read_json(study / 'comparison.json')
    schedule = comparison.get('schedule') or []
    result = {'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'study': str(study.resolve()),
              'scope': 'Recorded artifacts snapshot only; no failure-cause or stability inference.',
              'groups': {}, 'configuration': {}}
    configs = {}
    for arm in ('baseline', 'static'):
        configs[arm] = read_json(study / arm / 'frozen-agent/config.json')
        if not configs[arm]:
            configs[arm] = read_json(study / arm / 'study.json').get('sampling', {})
        keys = {(s['task'], s['number']) for s in schedule if s.get('arm') == arm}
        for directory in (study / arm / 'samples').glob('*'):
            if not directory.is_dir():
                continue
            sample = read_json(directory / 'sample.json')
            task, _, suffix = directory.name.rpartition('-')
            if sample.get('task') and sample.get('number') is not None:
                keys.add((sample['task'], sample['number']))
            elif suffix.isdigit():
                keys.add((task, int(suffix)))
        rows = []
        for task, index in sorted(keys):
            directory = study / arm / 'samples' / f'{task}-{index:02d}'
            sample = read_json(directory / 'sample.json')
            path = directory / 'evaluation' / task / 'development/run.log'
            row = {'sample': directory.name, 'task': task, 'number': index,
                   'sample_json_present': (directory / 'sample.json').exists(),
                   'status': sample.get('status', 'not_recorded'),
                   'passed': sample.get('passed'), 'score': sample.get('score'),
                   'sample_metadata': sample, 'log_present': path.exists()}
            if path.exists():
                try:
                    row['log'] = analyze_log(path)
                except (OSError, UnicodeError) as exc:
                    row['log_read_error'] = str(exc)
            rows.append(row)
        tasks = {}
        for task in sorted({r['task'] for r in rows}):
            subset = [r for r in rows if r['task'] == task]
            paused = [r for r in subset if r['status'] in PAUSED_STATUSES]
            finished = [r for r in subset if r['status'] not in {'running', 'not_recorded'} | PAUSED_STATUSES]
            passed = sum(r['passed'] is True for r in finished)
            tasks[task] = {'expected_or_observed': len(subset), 'finished': len(finished),
                           'passed': passed, 'success_rate': passed / len(finished) if finished else None,
                           'paused': len(paused), 'pending': len(subset) - len(finished) - len(paused)}
        logs = [r['log'] for r in rows if 'log' in r]
        contexts = [r['context'] for log in logs for r in log['requests']]
        result['groups'][arm] = {'tasks': tasks, 'samples': rows,
            'known_tokens': {key: sum(log['usage'][f'known_{key}'] for log in logs) for key in TOKEN_FIELDS},
            'token_field_missing_requests': {key: sum(not number(r['usage'].get(key))
                for log in logs for r in log['requests']) for key in TOKEN_FIELDS},
            'requests': sum(log['usage']['requests'] for log in logs),
            'requests_with_complete_usage': sum(log['usage']['requests_with_complete_usage'] for log in logs),
            'missing_logs': sum(not r['log_present'] for r in rows),
            'context_aggregate': aggregate_context(contexts),
            'errors': {key: sum(log.get('milestones', {}).get(key, 0) for log in logs)
                       for key in ('protocol_errors', 'tool_errors', 'infrastructure_errors')}}
    differences = {key: {'baseline': configs['baseline'].get(key), 'static': configs['static'].get(key)}
                   for key in sorted(set(configs['baseline']) | set(configs['static']))
                   if configs['baseline'].get(key) != configs['static'].get(key)}
    result['configuration'] = {'available': {arm: bool(configs[arm]) for arm in configs},
        'differences': differences,
        'only_static_context_compact_differs': bool(all(configs.values())) and
            set(differences) == {'static_context_compact'} and
            configs['baseline'].get('static_context_compact') is False and
            configs['static'].get('static_context_compact') is True,
        'context_accounting_enabled': {arm: configs[arm].get('context_accounting', True)
                                      if configs[arm] else None for arm in configs},
        'accounting_default_note': 'Absent context_accounting uses RequestAudit default True; actual records are counted separately.'}
    result['known_tokens'] = {key: sum(group['known_tokens'][key] for group in result['groups'].values())
                              for key in TOKEN_FIELDS}
    return result


def markdown(result):
    lines = ['# Context 对照记录', '', f"快照时间：{result['generated_at_utc']}", '',
        '仅汇总现有产物；未完成样本不计为失败。用户主动暂停单独统计，不当作失败，不计入成功率分母。成功率分母为已结束评测样本，缺失 usage 不估算。',
        '日志错误为观测计数，不据此推断失败原因或宣称稳定。字符计量不是 token 计量。', '',
        f"两组仅 static_context_compact 不同：{result['configuration']['only_static_context_compact_differs']}；"
        f"context_accounting 配置（缺省为开启）：{result['configuration']['context_accounting_enabled']}。", '',
        '| 组 | 题目 | 已结束/计划或观测 | 通过 | 成功率 | 已暂停 | 待完成 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for arm, group in result['groups'].items():
        for task, stats in group['tasks'].items():
            rate = f"{stats['success_rate']:.1%}" if stats['success_rate'] is not None else '未知'
            lines.append(f"| {arm} | {task} | {stats['finished']}/{stats['expected_or_observed']} | {stats['passed']} | {rate} | {stats['paused']} | {stats['pending']} |")
    lines += ['', '| 组 | 请求 | 完整 usage 请求 | 已知 prompt/completion/total tokens | 协议/工具/基础设施错误 |',
              '|---|---:|---:|---|---|']
    for arm, group in result['groups'].items():
        counts = '/'.join(str(group['known_tokens'][k]) for k in TOKENS)
        errors = '/'.join(str(v) for v in group['errors'].values())
        lines.append(f"| {arm} | {group['requests']} | {group['requests_with_complete_usage']} | {counts} | {errors} |")
    lines += ['', '| 组/样本 | 状态 | 通过/score | 请求 | 首改/末改/末改后末测/结束请求 | paper 页数/主题 |',
              '|---|---|---|---:|---|---|']
    for arm, group in result['groups'].items():
        for row in group['samples']:
            log = row.get('log', {})
            pos = log.get('positions', {})
            points = [str((pos.get(k) or {}).get('request', '—')) for k in ('first_write', 'last_write', 'last_test_after_last_write')]
            points.append(','.join(str(p.get('request')) for p in pos.get('finish', [])) or '—')
            inspection = log.get('inspection', {})
            paper = str(inspection.get('paper_page_count', '—')) + '/' + ', '.join(inspection.get('section_topics', []))
            lines.append(f"| {arm}/{row['sample']} | {row['status']} | {row['passed']}/{row['score']} | {log.get('usage', {}).get('requests', '—')} | {'/'.join(points)} | {paper} |")
    lines += ['', '| context 项 | baseline 已知字符合计/缺失请求 | static 已知字符合计/缺失请求 |',
              '|---|---:|---:|']
    for key in METRICS:
        cells = []
        for arm in ('baseline', 'static'):
            metric = result['groups'][arm]['context_aggregate'][key]
            cells.append(f"{metric['known_sum']}/{metric['missing_count']}")
        lines.append(f"| {key} | {' | '.join(cells)} |")
    lines += ['', 'context_accounting 为 text_json_chars 的逐项归属；JSON 包装单列。每请求原始 text_chars、usage 缺失、页码、主题、错误详情及各项 sum/count/missing/mean/max 见 CONTEXT-COMPARISON.json。', '',
              f"全部已知 tokens：{result['known_tokens']}。", '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('study', type=Path, nargs='?', default=DEFAULT_STUDY)
    parser.add_argument('--output-dir', type=Path, help='New report directory; default: new timestamped subdirectory in study')
    args = parser.parse_args()
    output = args.output_dir or args.study / ('analysis-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    targets = [output / 'CONTEXT-COMPARISON.json', output / 'REPORT.md']
    if any(p.exists() for p in targets):
        parser.error('Refusing to overwrite an existing report; choose a new output directory.')
    result = summarize(args.study)
    output.mkdir(parents=True, exist_ok=True)
    with targets[0].open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    with targets[1].open('x', encoding='utf-8') as stream:
        stream.write(markdown(result))
    print('\n'.join(str(p.resolve()) for p in targets))


if __name__ == '__main__':
    main()
