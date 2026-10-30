"""Exercise hidden grading isolation without invoking a provider."""
import json
from pathlib import Path

import pytest

import additional_stability as extra


@pytest.mark.parametrize('answer,passed', [(1, False), (2, True)])
def test_hidden_checks_run_only_after_agent_and_are_required(tmp_path, monkeypatch, answer, passed):
    root, study, bank = tmp_path / 'root', tmp_path / 'study', tmp_path / 'bank'
    (study / 'frozen-agent').mkdir(parents=True)
    (study / 'frozen-agent/config.json').write_text(json.dumps({'model': 'offline', 'key_env': 'OFFLINE_KEY'}))
    (study / 'frozen-agent/agent.py').write_text('# mocked Agent entrypoint')
    extra.course.save(study / 'study.json', {'runtime_sha256': extra.course.hashes(study / 'frozen-agent')})
    source = bank / 'sample'
    (source / 'repo').mkdir(parents=True)
    (source / 'reference').mkdir()
    (source / 'reference/a.py').write_text('REFERENCE_MUST_NOT_BE_VISIBLE')
    (source / 'repo/a.py').write_text('value = 0\n')
    (source / 'repo/test_visible.py').write_text('from a import value\ndef test_visible(): assert value > 0\n')
    (source / 'heldout_tests.py').write_text('from a import value\ndef test_hidden(): assert value == 2\n')
    (source / 'task.md').write_text('Set value to two, verify, and finish.')
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(extra.course, 'credentials', lambda *a: None)
    real_run = extra.course.run_logged
    phase = []
    def run(args, cwd, env, log, timeout=2400):
        if str(args[0]).endswith('agent.py'):
            repo = Path(args[args.index('--repo') + 1])
            assert not (repo / 'test_heldout.py').exists()
            assert not (repo / 'reference').exists()
            assert set(p.name for p in repo.iterdir()) == {'a.py', 'test_visible.py'}
            assert args[args.index('--profile') + 1] == 'generic'
            config = json.loads(Path(args[args.index('--config') + 1]).read_text())
            assert config['max_steps'] == 20
            (repo / 'a.py').write_text(f'value = {answer}\n')
            (cwd / 'run-result.json').write_text(json.dumps({'status': 'completed', 'reason': None}))
            events = [{'event': 'model_request', 'number': 1, 'body': {'messages': []}},
                      {'event': 'model_response', 'number': 1, 'response':
                       {'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}}]
            (cwd / 'run.log').write_text('\n'.join(json.dumps(e) for e in events))
            phase.append('agent_exited')
            return 0
        assert phase == ['agent_exited']
        assert (cwd / 'test_heldout.py').exists()
        assert not (cwd / 'reference').exists()
        return real_run(args, cwd, env, log, timeout)
    monkeypatch.setattr(extra.course, 'run_logged', run)
    result = extra.run_one(root, study, bank, {'id': 'sample', 'editable': ['a.py'], 'expected_tests': 2}, 1)
    assert result['passed'] is passed
    assert result['tests']['tests'] == 2
    assert result['tests']['failures'] == (0 if passed else 1)
    assert result['usage_complete'] is True and result['requests'] == 1
    assert result['forbidden_changes'] == []
    assert (Path(result['archive']) / 'run/run.log').exists()
