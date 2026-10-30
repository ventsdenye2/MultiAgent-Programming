"""Offline bank validation; never invokes agent.py or any model provider."""
import datetime
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


def fingerprint(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts
            and '.pytest_cache' not in p.parts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', action='append', help='Validate only selected task ids; repeatable')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / 'manifest.json').read_text())
    if args.task and set(args.task) - {task['id'] for task in manifest['tasks']}:
        parser.error('unknown task id')
    out = root / datetime.datetime.now().strftime('validation-%Y%m%d-%H%M%S-%f')
    out.mkdir()
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    env.pop('PYTHONPATH', None)
    summary = {'provider_calls': 0, 'python': sys.version, 'tasks': {}, 'ok': True}
    for task in manifest['tasks']:
        if args.task and task['id'] not in args.task:
            continue
        source = root / task['id']
        before = fingerprint(source)
        result = {}
        for variant in ('initial', 'reference'):
            for suite in ('visible', 'combined'):
                label = task['id'] + '-' + variant + '-' + suite
                with tempfile.TemporaryDirectory(prefix='stability-bank-') as temp:
                    repo = Path(temp) / 'repo'
                    shutil.copytree(source / 'repo', repo)
                    if variant == 'reference':
                        actual = {p.relative_to(source / 'reference').as_posix()
                                  for p in (source / 'reference').rglob('*.py')}
                        if actual != set(task['editable']):
                            raise RuntimeError('reference contains unexpected files: ' + task['id'])
                        for rel in task['editable']:
                            shutil.copy2(source / 'reference' / rel, repo / rel)
                    if suite == 'combined':
                        shutil.copy2(source / 'heldout_tests.py', repo / 'test_heldout.py')
                    xml = out / (label + '.xml')
                    command = [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                               '--junitxml', str(xml)]
                    run = subprocess.run(command, cwd=repo, env=env, capture_output=True,
                                         text=True, timeout=60)
                    (out / (label + '.log')).write_text(run.stdout + run.stderr, encoding='utf8')
                    tree = ET.parse(xml)
                    suites = tree.findall('.//testsuite')
                    counts = {key: sum(int(s.attrib.get(key, 0)) for s in suites)
                              for key in ('tests', 'failures', 'errors', 'skipped')}
                    valid = (run.returncode == 0 and counts['tests'] > 0 and
                             not any(counts[key] for key in ('failures', 'errors', 'skipped')))
                    expected = valid if variant == 'reference' else (
                        run.returncode == 1 and counts['failures'] > 0 and counts['errors'] == 0)
                    result[variant + '_' + suite] = {'exit_code': run.returncode, **counts,
                                                    'expected_result': expected}
                    summary['ok'] &= expected
        if fingerprint(source) != before:
            raise RuntimeError('bank inputs were modified: ' + task['id'])
        summary['tasks'][task['id']] = {'input_sha256': before, 'checks': result}
        (out / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf8')
        print(task['id'], json.dumps(result), flush=True)
    print('Results:', out, flush=True)
    return 0 if summary['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
