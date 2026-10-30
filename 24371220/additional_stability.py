"""Run original tasks with references excluded and held-out tests after Agent exit."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

import evaluate_course as course
from inspect_evaluation import inspect_log


def repo_hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()
            and not {'.pytest_cache', '__pycache__'}.intersection(p.parts)}


def run_one(root, study, bank, task, number):
    name = task['id']
    sample = study / 'samples' / f'extra-{name}-{number:02d}'
    source = bank / name
    native_base = Path.home() / '.local/state/code-agent/evaluations'
    native_base.mkdir(parents=True, exist_ok=True)
    native = Path(tempfile.mkdtemp(prefix=f'additional-{name}-{number:02d}-', dir=native_base))
    expected_runtime = json.loads((study / 'study.json').read_text())['runtime_sha256']
    if course.hashes(study / 'frozen-agent') != expected_runtime:
        raise RuntimeError('Frozen executable differs from the registered runtime')
    submission = native / 'submission'
    shutil.copytree(study / 'frozen-agent', submission)
    output, repo = native / 'run', native / 'repo'
    output.mkdir()
    shutil.copytree(source / 'repo', repo)
    shutil.copy2(source / 'task.md', native / 'task.md')
    before = repo_hashes(repo)
    config = json.loads((study / 'frozen-agent/config.json').read_text())
    config['max_steps'] = 20
    config['verify_commands'] = [['python', '-m', 'pytest', '-q']]
    course.save(native / 'generic-config.json', config)
    budget = native / 'request-budget.json'
    course.save(budget, {'limit': 20, 'used': 0})
    env = os.environ.copy()
    env.update(CODE_AGENT_ENGINE='smolagents', MINI_CONTEXT_MODE='evidence',
               PYTHONDONTWRITEBYTECODE='1', CODE_AGENT_REQUEST_BUDGET_FILE=str(budget))
    env.pop('PYTHONPATH', None)
    course.credentials(root, config, env)
    archive = sample / 'evaluation'
    course.save(sample / 'sample.json', {'task': name, 'number': number, 'status': 'running',
                                       'native': str(native), 'archive': str(archive)})
    result = {'task': name, 'number': number, 'status': 'failed', 'passed': False,
              'native': str(native), 'archive': str(archive), 'input_sha256': before,
              'profile': 'generic', 'max_requests': 20}
    try:
        rc = course.run_logged([submission / 'agent.py', '--task', native / 'task.md',
            '--repo', repo, '--model', config['model'], '--auto', '--profile', 'generic',
            '--allow', *task['editable'], '--config', native / 'generic-config.json'],
            output, env, native / 'agent-console.log', 2100)
        run_result = json.loads((output / 'run-result.json').read_text()) if (output / 'run-result.json').exists() else {}
        result.update(exit_code=rc, agent_status=run_result.get('status'), failure_reason=run_result.get('reason'))
        if (output / 'run.log').exists():
            inspection = inspect_log(output / 'run.log')
            course.save(native / 'inspection.json', inspection)
            result.update(requests=inspection['requests'], prompt_tokens=inspection['known_prompt_tokens'],
                completion_tokens=inspection['known_completion_tokens'], usage_complete=inspection['usage_complete'],
                max_request_chars=inspection['max_request_chars'], agent_errors=inspection['agent_error_types'])
        after = repo_hashes(repo)
        changed = {p for p in set(before) | set(after) if before.get(p) != after.get(p)}
        violations = sorted(changed - set(task['editable']))
        result.update(changed_files=sorted(changed), forbidden_changes=violations)
        # The model has exited. The held-out suite enters only a separate grading copy.
        validation = native / 'validation-repo'
        shutil.copytree(repo, validation, ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache'))
        shutil.copy2(source / 'heldout_tests.py', validation / 'test_heldout.py')
        check_env = env.copy()
        check_env.pop(config['key_env'], None)
        check_env.pop('CODE_AGENT_REQUEST_BUDGET_FILE', None)
        check_env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
        xml = native / 'grading.xml'
        tested = course.run_logged(['-m', 'pytest', '-q', '-p', 'no:cacheprovider', '--junitxml', xml],
                                  validation, check_env, native / 'grading.log', 120)
        counts = {}
        if xml.exists():
            suites = ET.parse(xml).findall('.//testsuite')
            counts = {k: sum(int(s.attrib.get(k, 0)) for s in suites)
                      for k in ('tests', 'failures', 'errors', 'skipped')}
        result.update(grading_exit_code=tested, tests=counts)
        result['runtime_unchanged'] = course.hashes(submission) == expected_runtime
        result['passed'] = bool(rc == 0 and run_result.get('status') == 'completed' and not violations
            and tested == 0 and counts.get('tests') == task['expected_tests']
            and not any(counts.get(k) for k in ('failures', 'errors', 'skipped'))
            and result['runtime_unchanged']
            and result.get('usage_complete') and 0 < result.get('requests', 0) <= 20
            and result.get('max_request_chars', 32001) <= 32000)
        result['status'] = 'passed' if result['passed'] else (
            'infrastructure_failure' if not result.get('usage_complete') else 'failed')
        if not result['passed'] and not result.get('failure_reason'):
            result['failure_reason'] = ('forbidden changes' if violations else
                'held-out/visible functional tests failed' if tested else 'Agent did not complete required process')
    except Exception as exc:
        result.update(status='infrastructure_failure', failure_reason=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        course.save(native / 'result.json', result)
        shutil.copytree(native, archive)
        course.save(sample / 'sample.json', result)
    return result


def run(root, study):
    from run_stability import assert_baseline, read, summarize
    source = root / 'stability_tasks'
    bank = study / 'frozen-tasks'
    if not bank.exists():
        manifest = read(source / 'manifest.json')
        validation = [read(p) for p in sorted(source.glob('validation-*/summary.json'))]
        checked = {}
        for report in validation:
            if report and report.get('ok'):
                checked.update(report['tasks'])
        for task in manifest['tasks']:
            actual = repo_hashes(source / task['id'])
            expected = checked.get(task['id'], {}).get('input_sha256')
            if actual != expected:
                raise RuntimeError('Task bank lacks matching successful offline oracle validation: ' + task['id'])
            task['expected_tests'] = checked[task['id']]['checks']['reference_combined']['tests']
        bank.mkdir()
        course.save(bank / 'manifest.json', manifest)
        for task in manifest['tasks']:
            shutil.copytree(source / task['id'], bank / task['id'],
                            ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache'))
        course.save(study / 'task-bank-sha256.json', repo_hashes(bank))
    expected = read(study / 'task-bank-sha256.json')
    manifest = read(bank / 'manifest.json')
    consecutive_infra = 0
    for number in range(1, 4):
        for task in manifest['tasks']:
            sample = study / 'samples' / f"extra-{task['id']}-{number:02d}"
            existing = read(sample / 'sample.json')
            if existing:
                if existing['status'] == 'running':
                    raise RuntimeError('Unresolved interrupted sample: ' + str(sample))
                continue
            assert_baseline(root, study)
            if repo_hashes(bank) != expected:
                raise RuntimeError('Frozen task bank changed')
            print(f"START extra {task['id']} {number}/3", flush=True)
            result = run_one(root, study, bank, task, number)
            summarize(study)
            print(f"DONE extra {task['id']} {number}/3 passed={result['passed']}", flush=True)
            if result['status'] == 'infrastructure_failure':
                consecutive_infra += 1
                if not result.get('requests') or consecutive_infra >= 3:
                    raise RuntimeError('Infrastructure failure; no more paid samples started')
            else:
                consecutive_infra = 0
    return 0
