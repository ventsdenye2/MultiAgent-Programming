"""Serial baseline/static comparison with frozen inputs and no replacement runs."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import evaluate_course as course
from run_stability import collect_sample, read, summarize


ARMS = ('baseline', 'static')
RUNNER_FILES = ('run_context_comparison.py', 'run_stability.py',
                'evaluate_course.py', 'inspect_evaluation.py')


def schedule():
    rows = []
    for number in range(1, 4):
        for task in ('source', 'paper'):
            order = ARMS if (number + (task == 'paper')) % 2 else ARMS[::-1]
            rows.extend({'arm': arm, 'task': task, 'number': number} for arm in order)
    return rows


def file_hashes(root, names):
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}


def freeze(root, study, commit, materials):
    if study.exists():
        raise RuntimeError('New comparison directory must not already exist')
    study.mkdir(parents=True)
    original_config = read(root / 'config.json')
    for arm in ARMS:
        frozen = study / arm / 'frozen-agent'
        frozen.parent.mkdir()
        course.copy_submission(root, frozen)
        config = read(frozen / 'config.json')
        if config != original_config:
            raise RuntimeError('Source configuration changed during freezing')
        config['static_context_compact'] = arm == 'static'
        course.save(frozen / 'config.json', config)
        course.save(frozen.parent / 'study.json', {
            'baseline_commit': commit, 'runtime_sha256': course.hashes(frozen),
            'sampling': config, 'course_repetitions': 3,
            'course_request_caps': {'source': 20, 'paper': 40},
            'automatic_retries': False})
    baseline = read(study / 'baseline/study.json')['runtime_sha256']
    optimized = read(study / 'static/study.json')['runtime_sha256']
    assert {k: v for k, v in baseline.items() if k != 'config.json'} == {
        k: v for k, v in optimized.items() if k != 'config.json'}
    source_hashes = file_hashes(root, baseline)
    if any(source_hashes[name] != value for name, value in baseline.items() if name != 'config.json'):
        raise RuntimeError('Source runtime changed during freezing')
    manifest = {'implementation_commit': commit, 'schedule': schedule(),
                'sample_count': 12, 'request_upper_bound': 360,
                'materials': str(materials), 'course_sha256': course.hashes(materials),
                'runner_sha256': file_hashes(root, RUNNER_FILES),
                'source_runtime_sha256': source_hashes,
                'provenance': 'Host-verified Git checkpoint plus captured runtime and runner hashes; existing runner changes are included by hash.',
                'automatic_retries': False}
    course.save(study / 'comparison.json', manifest)
    return manifest


def verify_inputs(root, study, manifest):
    if manifest['schedule'] != schedule():
        raise RuntimeError('Comparison schedule changed')
    if file_hashes(root, RUNNER_FILES) != manifest['runner_sha256']:
        raise RuntimeError('Comparison runner changed')
    if course.hashes(Path(manifest['materials'])) != manifest['course_sha256']:
        raise RuntimeError('Course materials changed')
    for arm in ARMS:
        expected = read(study / arm / 'study.json')['runtime_sha256']
        if course.hashes(study / arm / 'frozen-agent') != expected:
            raise RuntimeError('Frozen runtime changed: ' + arm)


def next_sample(study, manifest):
    for row in manifest['schedule']:
        sample = study / row['arm'] / 'samples' / f"{row['task']}-{row['number']:02d}"
        result = read(sample / 'sample.json')
        if result is None:
            return row, sample
        if result['status'] == 'running':
            raise RuntimeError('Unresolved interrupted sample: ' + str(sample))
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-paid', action='store_true')
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--baseline-commit', required=True)
    parser.add_argument('--max-new-samples', type=int, default=1)
    args = parser.parse_args()
    if not args.run_paid or sys.platform != 'linux':
        parser.error('WSL and --run-paid are required')
    if not re.fullmatch('[0-9a-f]{40}', args.baseline_commit) or args.max_new_samples < 1:
        parser.error('Provide a full commit and a positive sample limit')
    root = Path(__file__).resolve().parent
    study = args.study.resolve()
    materials = Path(os.environ.get('COURSE_MATERIALS', root.parents[2] / '题目要求/02')).resolve()
    with (root / 'experiments/smolagents/.evaluation.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another evaluation is active; no request started')
        manifest = read(study / 'comparison.json')
        if manifest is None:
            manifest = freeze(root, study, args.baseline_commit, materials)
        if manifest['implementation_commit'] != args.baseline_commit:
            raise RuntimeError('Implementation commit differs from frozen comparison')
        verify_inputs(root, study, manifest)
        # execute() copies from the frozen arm; retain the original workspace's
        # material and credential lookup rather than depending on snapshot depth.
        os.environ['COURSE_MATERIALS'] = manifest['materials']
        course.credentials(root, read(study / 'baseline/frozen-agent/config.json'), os.environ)
        for _ in range(args.max_new_samples):
            pending = next_sample(study, manifest)
            if pending is None:
                print('COMPARISON COMPLETE', flush=True)
                return 0
            row, sample = pending
            verify_inputs(root, study, manifest)
            task, arm = row['task'], row['arm']
            native_base = Path.home() / '.local/state/code-agent/evaluations'
            native_base.mkdir(parents=True, exist_ok=True)
            native = Path(tempfile.mkdtemp(prefix=f'context-{arm}-{task}-', dir=native_base))
            filesystem = subprocess.check_output(['stat', '-f', '-c', '%T', str(native)], text=True).strip()
            if filesystem not in {'ext2/ext3', 'tmpfs', 'btrfs', 'xfs'}:
                raise RuntimeError('Native Linux filesystem required')
            archive = sample / 'evaluation'
            course.save(sample / 'sample.json', {**row, 'status': 'running', 'native': str(native)})
            print(f"START {arm} {task} {row['number']}/3 native={native}", flush=True)
            try:
                rc = course.execute(study / arm / 'frozen-agent', native, archive, False,
                                    task, 20 if task == 'source' else 40)
            except Exception as exc:
                course.save(sample / 'exception.json', {'type': type(exc).__name__, 'message': str(exc)})
                rc = 2
            result = collect_sample(sample, task, rc, archive)
            result.update(row, native=str(native))
            course.save(sample / 'sample.json', result)
            summarize(study / arm)
            verify_inputs(root, study, manifest)
            print(f"DONE {arm} {task} {row['number']}/3 passed={result['passed']} requests={result.get('requests')}", flush=True)
            if result['status'] == 'infrastructure_failure':
                print('INFRASTRUCTURE REVIEW BOUNDARY; sample retained', flush=True)
                return 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
