"""Fixed-version, serial real evaluations. Explicit --run-paid, no sample retries."""
import argparse
from collections import Counter
import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import evaluate_course as course
from inspect_evaluation import inspect_log


def read(path, fallback=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return fallback


def interval(passed, count):
    if not count:
        return None
    z = 1.959963984540054
    p = passed / count
    center = (p + z*z/(2*count)) / (1 + z*z/count)
    margin = z * math.sqrt(p*(1-p)/count + z*z/(4*count*count)) / (1 + z*z/count)
    return [center-margin, center+margin]


def summarize(study):
    manifest = read(study / 'study.json')
    rows = [read(p) for p in sorted((study / 'samples').glob('*/sample.json'))]
    groups = {}
    for name in sorted({r['task'] for r in rows}):
        done = [r for r in rows if r['task'] == name and r['status'] != 'running']
        passed = sum(r.get('passed') is True for r in done)
        groups[name] = {'finished': len(done), 'passed': passed,
                        'success_rate': passed/len(done) if done else None,
                        'wilson_95': interval(passed, len(done)),
                        'failure_reasons': dict(Counter(r.get('failure_reason') or r['status']
                                                  for r in done if not r.get('passed')))}
    report = {'baseline_commit': manifest['baseline_commit'], 'groups': groups,
              'requests': sum(r.get('requests', 0) for r in rows),
              'prompt_tokens': sum(r.get('prompt_tokens', 0) for r in rows),
              'completion_tokens': sum(r.get('completion_tokens', 0) for r in rows),
              'usage_complete': all(r.get('usage_complete', False) for r in rows if r['status'] != 'running'),
              'rows': rows}
    course.save(study / 'summary.json', report)
    lines = ['# Fixed-version stability study', '',
             'Baseline: `' + manifest['baseline_commit'] + '`; context_mode=evidence.', '',
             '| Task | Passed / finished | Success rate | Wilson 95% interval |',
             '|---|---:|---:|---:|']
    for name, g in groups.items():
        ci = g['wilson_95']
        lines.append(f"| {name} | {g['passed']}/{g['finished']} | " +
                     (f"{g['success_rate']:.1%} | {ci[0]:.1%}–{ci[1]:.1%} |" if ci else 'pending | pending |'))
    lines += ['', f"Actual requests: {report['requests']}; known input/output tokens: "
              f"{report['prompt_tokens']}/{report['completion_tokens']}; usage complete: {report['usage_complete']}.",
              '', 'All scheduled attempts count, including failures. No replacement samples or within-cohort code fixes.',
              'Intervals quantify sampling uncertainty for these tasks; this is not a guarantee on arbitrary tasks.']
    (study / 'SUMMARY.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return report


def assert_baseline(root, study):
    manifest = read(study / 'study.json')
    for name, expected in manifest['runtime_sha256'].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Frozen runtime changed: ' + name)


def collect_sample(sample, task, rc, archive):
    spec = {'task': task, 'exit_code': rc, 'archive': str(archive), 'status': 'failed', 'passed': False}
    protocol = read(archive / 'protocol.json', {})
    result = read(archive / task / 'result.json', {})
    log = archive / task / 'development/run.log'
    if log.exists():
        report = inspect_log(log)
        course.save(sample / 'inspection.json', report)
        spec.update(requests=report['requests'], prompt_tokens=report['known_prompt_tokens'],
                    completion_tokens=report['known_completion_tokens'], usage_complete=report['usage_complete'],
                    max_request_chars=report['max_request_chars'], agent_errors=report['agent_error_types'],
                    failure_reason=(report['result'] or {}).get('reason'),
                    agent_status=(report['result'] or {}).get('status'))
    spec.update(score=result.get('score'), max_score=result.get('max_score'), checks=result.get('checks'))
    spec['passed'] = bool(rc == 0 and result.get('passed') is True and
                          spec.get('agent_status') == 'completed' and spec.get('usage_complete'))
    spec['status'] = 'passed' if spec['passed'] else ('infrastructure_failure'
                       if protocol.get('status') in {'failed', 'infrastructure_failure', 'interrupted'} else 'failed')
    return spec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-paid', action='store_true')
    parser.add_argument('--study', type=Path)
    parser.add_argument('--phase', choices=['course', 'additional', 'summary'], default='course')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if args.phase == 'summary':
        print(json.dumps(summarize(args.study), ensure_ascii=False, indent=2))
        return 0
    if not args.run_paid or sys.platform != 'linux':
        parser.error('Real runs require WSL and explicit --run-paid')
    lock = (root / 'experiments/smolagents/.evaluation.lock').open('a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Another evaluation is active; no new request started')
    study = (args.study or root / 'experiments/smolagents' / datetime.datetime.now().strftime('stability-%Y%m%d-%H%M%S')).resolve()
    if not (study / 'study.json').exists():
        study.mkdir(parents=True, exist_ok=False)
        fingerprint = course.copy_submission(root, study / 'frozen-agent')
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
        course.save(study / 'study.json', {'baseline_commit': commit, 'runtime_sha256': fingerprint,
            'course_repetitions': 20, 'additional_repetitions': 3,
            'course_request_caps': {'source': 20, 'paper': 40}, 'additional_request_cap': 20,
            'total_request_upper_bound': 1500, 'context_mode': 'evidence',
            'automatic_retries': False, 'sampling': read(root / 'config.json')})
    print('STUDY ' + str(study), flush=True)
    assert_baseline(root, study)
    if args.phase == 'additional':
        raise SystemExit('Additional harness is prepared separately after task oracle validation; no requests started')
    consecutive_infra = 0
    for number in range(1, 21):
        for task, cap in [('source', 20), ('paper', 40)]:
            sample = study / 'samples' / f'{task}-{number:02d}'
            existing = read(sample / 'sample.json')
            if existing:
                if existing['status'] == 'running':
                    raise RuntimeError('Unresolved interrupted sample; inspect before continuing: ' + str(sample))
                continue
            assert_baseline(root, study)
            native_base = Path.home() / '.local/state/code-agent/evaluations'
            native_base.mkdir(parents=True, exist_ok=True)
            native = Path(tempfile.mkdtemp(prefix=f'stability-{task}-{number:02d}-', dir=native_base))
            fs = subprocess.check_output(['stat', '-f', '-c', '%T', str(native)], text=True).strip()
            if fs not in {'ext2/ext3', 'tmpfs', 'btrfs', 'xfs'}:
                raise RuntimeError('Native Linux filesystem required')
            archive = sample / 'evaluation'
            course.save(sample / 'sample.json', {'task': task, 'number': number, 'status': 'running',
                        'native': str(native), 'archive': str(archive)})
            print(f'START {task} {number}/20 native={native}', flush=True)
            try:
                rc = course.execute(root, native, archive, False, task, cap)
            except Exception as exc:
                rc = 2
                course.save(sample / 'exception.json', {'type': type(exc).__name__, 'message': str(exc)})
            result = collect_sample(sample, task, rc, archive)
            result.update(number=number, native=str(native))
            course.save(sample / 'sample.json', result)
            summarize(study)
            print(f"DONE {task} {number}/20 passed={result['passed']} requests={result.get('requests', 0)}", flush=True)
            assert_baseline(root, study)
            if result['status'] == 'infrastructure_failure':
                consecutive_infra += 1
                if not result.get('requests') or consecutive_infra >= 3:
                    raise RuntimeError('Infrastructure failure; no further paid samples started')
            else:
                consecutive_infra = 0
    print('COURSE COHORT COMPLETE ' + str(study), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
