"""Offline protection against expanding, replacing or mutating paid samples."""
from collections import Counter

import pytest

import run_context_comparison as runner


def test_schedule_has_three_per_arm_task_and_alternates():
    rows = runner.schedule()
    assert len(rows) == 12
    assert Counter((r['arm'], r['task']) for r in rows) == {
        ('baseline', 'source'): 3, ('static', 'source'): 3,
        ('baseline', 'paper'): 3, ('static', 'paper'): 3}
    assert sum(20 if r['task'] == 'source' else 40 for r in rows) == 360
    assert [r['arm'] for r in rows[:4]] == ['baseline', 'static', 'static', 'baseline']


def test_resume_preserves_failures_and_blocks_unresolved_sample(tmp_path):
    manifest = {'schedule': runner.schedule()}
    row, sample = runner.next_sample(tmp_path, manifest)
    runner.course.save(sample / 'sample.json', {**row, 'status': 'failed'})
    next_row, next_path = runner.next_sample(tmp_path, manifest)
    assert next_row['arm'] == 'static' and next_row['task'] == 'source'
    runner.course.save(next_path / 'sample.json', {**next_row, 'status': 'running'})
    with pytest.raises(RuntimeError, match='Unresolved interrupted sample'):
        runner.next_sample(tmp_path, manifest)


def test_freeze_only_changes_prompt_switch_and_detects_material_drift(tmp_path, monkeypatch):
    root = tmp_path / 'root'
    root.mkdir()
    runner.course.save(root / 'config.json', {'model': 'fixed'})
    (root / 'agent.py').write_text('agent', encoding='utf-8')
    for name in runner.RUNNER_FILES:
        (root / name).write_text('runner', encoding='utf-8')
    materials = tmp_path / 'materials'
    materials.mkdir()
    (materials / 'task.md').write_text('requirements', encoding='utf-8')

    def copy_submission(root, target):
        target.mkdir()
        runner.course.save(target / 'config.json', {'model': 'fixed'})
        (target / 'agent.py').write_text('agent', encoding='utf-8')

    monkeypatch.setattr(runner.course, 'copy_submission', copy_submission)
    study = tmp_path / 'study'
    manifest = runner.freeze(root, study, 'a' * 40, materials)
    runner.verify_inputs(root, study, manifest)
    configs = [runner.read(study / arm / 'frozen-agent/config.json') for arm in runner.ARMS]
    assert configs == [{'model': 'fixed', 'static_context_compact': False},
                       {'model': 'fixed', 'static_context_compact': True}]
    (materials / 'task.md').write_text('new requirements', encoding='utf-8')
    with pytest.raises(RuntimeError, match='Course materials changed'):
        runner.verify_inputs(root, study, manifest)
    with pytest.raises(RuntimeError, match='must not already exist'):
        runner.freeze(root, study, 'a' * 40, materials)
