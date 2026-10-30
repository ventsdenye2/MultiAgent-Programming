"""No-provider tests for fixed cohort size, resume and failure accounting."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

import run_stability as runner


def fixture_study(tmp_path, monkeypatch):
    root = tmp_path / 'agent'
    root.mkdir()
    (root / 'experiments/smolagents').mkdir(parents=True)
    (root / 'runtime.txt').write_text('frozen')
    study = root / 'study'
    runner.course.save(study / 'study.json', {'baseline_commit': 'fixed',
        'runtime_sha256': {'runtime.txt': hashlib.sha256(b'frozen').hexdigest()}})
    monkeypatch.setattr(runner, '__file__', str(root / 'run_stability.py'))
    monkeypatch.setattr(sys, 'argv', ['run_stability.py', '--run-paid', '--study', str(study)])
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(runner.subprocess, 'check_output', lambda *a, **k: 'ext2/ext3\n')
    return root, study


def test_declared_failures_count_and_resume_does_not_repeat(tmp_path, monkeypatch):
    root, study = fixture_study(tmp_path, monkeypatch)
    attempts = []
    def execute(root, native, archive, preflight, task, cap):
        attempts.append((task, cap, str(native), str(archive)))
        return 1 if task == 'source' else 0
    monkeypatch.setattr(runner.course, 'execute', execute)
    monkeypatch.setattr(runner, 'collect_sample', lambda sample, task, rc, archive:
        {'task': task, 'status': 'failed' if rc else 'passed', 'passed': rc == 0,
         'requests': 1, 'prompt_tokens': 10, 'completion_tokens': 2, 'usage_complete': True,
         'failure_reason': 'task failure' if rc else None})
    assert runner.main() == 0
    assert len(attempts) == 20 and len({a[2] for a in attempts}) == 20
    assert attempts[:2][0][:2] == ('source', 20)
    assert attempts[:2][1][:2] == ('paper', 40)
    report = runner.read(study / 'summary.json')
    assert report['groups']['source']['finished'] == 10
    assert report['groups']['source']['passed'] == 0
    assert report['groups']['paper']['passed'] == 10
    assert report['requests'] == 20
    assert runner.main() == 0 and len(attempts) == 20


def test_changed_runtime_and_interrupted_sample_stop_before_provider(tmp_path, monkeypatch):
    root, study = fixture_study(tmp_path, monkeypatch)
    def forbidden(*a, **k):
        pytest.fail('No paid execution may begin')
    monkeypatch.setattr(runner.course, 'execute', forbidden)
    (root / 'runtime.txt').write_text('changed')
    with pytest.raises(RuntimeError, match='Frozen runtime changed'):
        runner.main()
    (root / 'runtime.txt').write_text('frozen')
    runner.course.save(study / 'samples/source-01/sample.json', {'task': 'source', 'status': 'running'})
    with pytest.raises(RuntimeError, match='Unresolved interrupted sample'):
        runner.main()


def test_success_interval_does_not_claim_certainty():
    low, high = runner.interval(20, 20)
    assert 0.83 < low < 0.85 and high <= 1.0000000001
    assert runner.interval(0, 0) is None


def test_three_per_task_is_frozen_and_cannot_expand_on_resume(tmp_path, monkeypatch):
    root, study = fixture_study(tmp_path, monkeypatch)
    manifest = runner.read(study / 'study.json')
    manifest['course_repetitions'] = 3
    runner.course.save(study / 'study.json', manifest)
    monkeypatch.setattr(sys, 'argv', ['run_stability.py', '--run-paid', '--study', str(study),
                                     '--repetitions', '3'])
    calls = []
    monkeypatch.setattr(runner.course, 'execute', lambda *a: calls.append(a) or 0)
    monkeypatch.setattr(runner, 'collect_sample', lambda sample, task, rc, archive:
                        {'task': task, 'status': 'passed', 'passed': True, 'usage_complete': True})
    assert runner.main() == 0
    assert len(calls) == 6
    assert runner.main() == 0 and len(calls) == 6
    monkeypatch.setattr(sys, 'argv', ['run_stability.py', '--run-paid', '--study', str(study),
                                     '--repetitions', '10'])
    with pytest.raises(RuntimeError, match='repetitions differ'):
        runner.main()
    assert len(calls) == 6


def test_review_boundary_starts_only_next_unfinished_sample(tmp_path, monkeypatch):
    root, study = fixture_study(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, 'argv', ['run_stability.py', '--run-paid', '--study', str(study),
                                     '--max-new-samples', '1'])
    tasks = []
    monkeypatch.setattr(runner.course, 'execute', lambda root, native, archive, preflight, task, cap:
                        tasks.append(task) or 1)
    monkeypatch.setattr(runner, 'collect_sample', lambda sample, task, rc, archive:
                        {'task': task, 'status': 'failed', 'passed': False, 'usage_complete': True})
    assert runner.main() == 0
    assert tasks == ['source']
    assert runner.main() == 0
    assert tasks == ['source', 'paper']


def test_host_verified_commit_creates_cohort_without_wsl_git(tmp_path, monkeypatch):
    root, unused = fixture_study(tmp_path, monkeypatch)
    study = root / 'new-study'
    sha = 'a' * 40
    monkeypatch.setattr(sys, 'argv', ['run_stability.py', '--run-paid', '--study', str(study),
                                     '--baseline-commit', sha])
    monkeypatch.setattr(runner.course, 'copy_submission', lambda root, target: {})
    calls = []
    monkeypatch.setattr(runner.course, 'execute', lambda *a: calls.append(a) or 0)
    monkeypatch.setattr(runner, 'collect_sample', lambda sample, task, rc, archive:
                        {'task': task, 'status': 'passed', 'passed': True, 'usage_complete': True})
    assert runner.main() == 0
    assert len(calls) == 20
    assert runner.read(study / 'study.json')['baseline_commit'] == sha
