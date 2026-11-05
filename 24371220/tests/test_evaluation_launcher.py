"""Offline launch orchestration, preflight gating and archival failures."""
import json
from pathlib import Path
import pytest
import evaluate_long_context_v2 as launch


def setup(tmp_path, monkeypatch):
    root = tmp_path / 'workspace/agents/code-agent/24371220'
    root.mkdir(parents=True)
    (root / 'codeagent').mkdir()
    (root / 'agent.py').write_text('# offline')
    (root / 'config.json').write_text(json.dumps({'model':'fake','key_env':'OFFLINE_KEY'}))
    course = root.parents[2] / '题目要求/02'
    course.mkdir(parents=True)
    (course / 'eval_paper.py').write_text('# unchanged course')
    native = tmp_path / 'native'
    native.mkdir()
    archive = tmp_path / 'archive'
    monkeypatch.setattr(launch, 'credentials', lambda *_: None)
    return root, native, archive


def test_preflight_failure_never_calls_model_and_archives(tmp_path, monkeypatch):
    root, native, archive = setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(launch, 'run_logged', lambda *a: calls.append(a))
    def fail(*_):
        raise RuntimeError('PDF preflight failed')
    monkeypatch.setattr(launch, 'preflight', fail)
    with pytest.raises(RuntimeError):
        launch.execute(root, native, archive)
    assert calls == []
    assert json.loads((archive/'protocol.json').read_text())['status'] == 'failed'
    assert (native/'results/protocol.json').is_file()


def test_preflight_only_never_loads_key_or_runs_evaluator(tmp_path, monkeypatch):
    root, native, archive = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(launch, 'preflight', lambda *_: {'status':'passed'})
    def forbidden(*_):
        pytest.fail('paid branch entered')
    monkeypatch.setattr(launch, 'credentials', forbidden)
    monkeypatch.setattr(launch, 'run_logged', forbidden)
    assert launch.execute(root, native, archive, True) == 0
    assert json.loads((archive/'protocol.json').read_text())['status'] == 'preflight_passed'


@pytest.mark.parametrize('infra,expected', [(True, ['eval_deepinfer.py']),
                                          (False, ['eval_deepinfer.py','eval_paper.py'])])
def test_source_failure_controls_paper_stage(tmp_path, monkeypatch, infra, expected):
    root, native, archive = setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(launch, 'preflight', lambda *_: {'status':'passed'})
    monkeypatch.setattr(launch, 'run_logged', lambda args,*_: calls.append(args[0]) or 1)
    monkeypatch.setattr(launch, 'infrastructure_failure', lambda *_: infra)
    assert launch.execute(root, native, archive) == (2 if infra else 1)
    assert calls == expected


def test_archive_failure_keeps_native_output(tmp_path, monkeypatch):
    root, native, archive = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(launch, 'preflight', lambda *_: {'status':'passed'})
    archive.mkdir()  # Never overwrite an existing archive.
    (archive/'keep.txt').write_text('untouched')
    assert launch.execute(root, native, archive, True) == 0
    assert json.loads((native/'results/archive-status.json').read_text())['status'] == 'failed'
    assert (archive/'keep.txt').read_text() == 'untouched'


def test_agent_timeout_is_infrastructure_even_if_course_scores_zero(tmp_path):
    (tmp_path/'development').mkdir()
    (tmp_path/'result.json').write_text('{"status":"complete","score":0}')
    p = tmp_path/'development/run-result.json'
    p.write_text(json.dumps({'reason':'MODEL_REQUEST_FAILED: timed out','usage':{'complete':False}}))
    assert launch.infrastructure_failure(tmp_path, 1)
    p.write_text(json.dumps({'reason':'MODEL_BUDGET_EXHAUSTED','usage':{'complete':True}}))
    assert not launch.infrastructure_failure(tmp_path, 1)


def test_interrupt_preserves_protocol_and_archive(tmp_path, monkeypatch):
    root, native, archive = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(launch, 'preflight', lambda *_: {'status':'passed'})
    def interrupt(*_):
        raise KeyboardInterrupt()
    monkeypatch.setattr(launch, 'run_logged', interrupt)
    with pytest.raises(KeyboardInterrupt):
        launch.execute(root, native, archive)
    assert json.loads((archive/'protocol.json').read_text())['status'] == 'interrupted'


def test_subprocess_timeout_retains_output(tmp_path, monkeypatch):
    import os
    import subprocess
    log = tmp_path/'process.log'
    stopped = []
    class Process:
        pid = 12345
        waits = 0
        def __init__(self, args, **kwargs):
            kwargs['stdout'].write('started\n')
        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired('offline', timeout)
            return -15
        def terminate(self):
            stopped.append('terminated')
    monkeypatch.setattr(launch.subprocess, 'Popen', Process)
    if launch.sys.platform == 'linux':
        monkeypatch.setattr(launch.os, 'killpg', lambda *args: stopped.append(args))
    with pytest.raises(subprocess.TimeoutExpired):
        launch.run_logged(['-u','-c',"import time; print('started'); time.sleep(5)"],
                          tmp_path, os.environ.copy(), log, timeout=0.5)
    assert 'started' in log.read_text()
    assert len(stopped) == 1
