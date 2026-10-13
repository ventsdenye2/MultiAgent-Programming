#!/usr/bin/env python3
"""公开题评测内核；从本目录读取题目、测试和规则，检查功能与过程。"""
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parent))
from contracts import read_events, inspect_process

AGENT_TIMEOUT = 600
PYTEST_TIMEOUT = 120
IGNORED = {'__pycache__', '.pytest_cache', '.git'}


def check_environment():
    """启动前检查评测环境；配置错误不生成成绩。"""
    if not shutil.which('patch'):
        raise ValueError('缺少 GNU patch，请先安装 patch 命令')
    for package in ('pytest',):
        try:
            metadata.version(package)
        except metadata.PackageNotFoundError:
            raise ValueError(f'缺少 {package}，请激活课程环境，并在课程材料根目录运行 '
                             'python -m pip install -r requirements.txt') from None


def collect_usage(log_path):
    """汇总 API 上报的 token；缺失/损坏记录不会冒充零消耗。"""
    fields = ('prompt_tokens', 'completion_tokens', 'total_tokens')
    counts = dict.fromkeys(fields, 0)
    requests, records, bad = 0, 0, 0
    models = set()
    if log_path.is_file() and not log_path.is_symlink():
        try:
            lines = log_path.read_text(encoding='utf-8').splitlines()
        except (OSError, UnicodeError):
            lines, bad = [], 1
        for line in lines:
            try:
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError('event must be an object')
            except (ValueError, TypeError):
                bad += 1
                continue
            if event.get('event') == 'model_request':
                requests += 1
            if event.get('event') != 'usage':
                continue
            usage = event.get('usage')
            if not isinstance(usage, dict) or not all(
                    type(usage.get(k)) is int and usage[k] >= 0 for k in fields):
                bad += 1
                continue
            if usage['total_tokens'] != usage['prompt_tokens'] + usage['completion_tokens']:
                bad += 1
                continue
            records += 1
            for k in fields:
                counts[k] += usage[k]
            if isinstance(event.get('actual_model'), str):
                models.add(event['actual_model'])
    return {**{k: counts[k] if records else '' for k in fields},
            'model_requests': requests, 'usage_records': records,
            'usage_complete': bool(requests and records == requests and not bad),
            'usage_parse_errors': bad, 'returned_models': ';'.join(sorted(models))}


def run_process(cmd, cwd, timeout, env=None):
    start = time.monotonic()
    env = dict(os.environ) if env is None else dict(env)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding='utf-8',
                            errors='replace', start_new_session=True, stdin=subprocess.DEVNULL)
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = proc.communicate()
        if isinstance(exc, KeyboardInterrupt):
            raise
        timed_out = True
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return dict(rc=124 if timed_out else proc.returncode,
                elapsed_s=time.monotonic() - start, stdout=stdout,
                stderr=stderr, timeout=timed_out)


def run_agent(agent_py, model, task_md, work_repo, run_dir, timeout=AGENT_TIMEOUT):
    cmd = [sys.executable, str(agent_py.resolve()), '--task', str(task_md.resolve()),
           '--repo', str(work_repo.resolve()), '--model', model, '--auto']
    # 智能体按配置接入 API；继承当前终端环境，评测器不选择服务商或 SDK。
    result = run_process(cmd, run_dir, timeout)
    result['unsafe_artifacts'] = []
    for stream in ('stdout', 'stderr'):
        path = run_dir / f'agent_{stream}.txt'
        if path.exists() or path.is_symlink():
            result['unsafe_artifacts'].append('reserved_artifact:' + path.name)
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        path.write_text(result[stream], encoding='utf-8')
    return result


def snapshot(repo):
    return {p.relative_to(repo).as_posix(): (b'\x00SYMLINK:' + os.readlink(p).encode()
            if p.is_symlink() else p.read_bytes()) for p in repo.rglob('*')
            if (p.is_file() or p.is_symlink()) and not any(
                part in IGNORED for part in p.relative_to(repo).parts)}


def check_patch(before, after, patch, run_dir):
    if not patch.is_file() or patch.is_symlink():
        return False
    with tempfile.TemporaryDirectory(prefix='patch-verify-') as tmp:
        repo = Path(tmp)
        for name, content in before.items():
            dest = repo / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        result = run_process(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch.resolve())], repo, 30)
        (run_dir / 'patch_check.txt').write_text(result['stdout'] + result['stderr'], encoding='utf-8')
        return result['rc'] == 0 and snapshot(repo) == after


def validation_stats(xml_path):
    stats = dict(passed=0, failed=0, errors=0, skipped=0, tests=0)
    try:
        for suite in ET.parse(xml_path).getroot().iter('testsuite'):
            for key, attr in (('tests', 'tests'), ('failed', 'failures'),
                              ('errors', 'errors'), ('skipped', 'skipped')):
                stats[key] += int(suite.get(attr, '0'))
        stats['passed'] = stats['tests'] - stats['failed'] - stats['errors'] - stats['skipped']
        return stats, stats['tests'] > 0 and all(value >= 0 for value in stats.values())
    except (OSError, ET.ParseError, ValueError):
        return stats, False


def run_validation(case_dir, work_repo, run_dir, timeout=PYTEST_TIMEOUT, key_env=None):
    # 从原始题目复制公开测试，在独立目录运行；不加载待测仓库内的 pytest 配置/conftest。
    with tempfile.TemporaryDirectory(prefix='trusted-validation-') as tmp:
        trusted = Path(tmp)
        (trusted / 'tests').mkdir()
        for test in (case_dir / 'repo').rglob('test_*.py'):
            target = trusted / 'tests' / test.relative_to(case_dir / 'repo')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(test, target)
        (trusted / 'pytest.ini').write_text('[pytest]\n', encoding='utf-8')
        env = {k: v for k, v in os.environ.items() if not k.endswith('_API_KEY') and k != key_env}
        env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONPATH=str(work_repo.resolve()))
        env.pop('PYTEST_ADDOPTS', None)
        xml_path = trusted / 'results.xml'
        command = [sys.executable, '-m', 'pytest', '-q', '--tb=short',
                   '-c', str(trusted / 'pytest.ini'), '--confcutdir', str(trusted),
                   '--junitxml', str(xml_path), str(trusted / 'tests')]
        deadline = time.monotonic() + timeout
        result = run_process(command, trusted, timeout, env)
        stats, report_valid = validation_stats(xml_path)
        if xml_path.exists():
            shutil.copy2(xml_path, run_dir / 'junit.xml')
        status = 'passed' if result['rc'] == 0 and stats['passed'] > 0 and not any(
            stats[k] for k in ('failed', 'errors', 'skipped')) else 'validation_failed'
        if result['timeout']:
            status = 'validation_timeout'
        elif not report_valid or result['rc'] not in (0, 1, 2):
            status = 'validation_error'
        elif result['rc'] == 2 or stats['errors']:
            # 同环境下初始代码能运行测试，才把收集/导入/运行错误归因于提交代码。
            status = 'validation_error'
            remaining = deadline - time.monotonic()
            if remaining > 0:
                original_env = {**env, 'PYTHONPATH': str((case_dir / 'repo').resolve())}
                original_xml = trusted / 'original-results.xml'
                original_command = command.copy()
                original_command[original_command.index(str(xml_path))] = str(original_xml)
                original = run_process(original_command, trusted, remaining, original_env)
                original_stats, original_valid = validation_stats(original_xml)
                (run_dir / 'validation_baseline_output.txt').write_text(
                    original['stdout'] + original['stderr'], encoding='utf-8')
                if (not original['timeout'] and original['rc'] in (0, 1) and original_valid
                        and not original_stats['errors'] and not original_stats['skipped']):
                    status = 'validation_failed'
        (run_dir / 'pytest_output.txt').write_text(result['stdout'] + result['stderr'], encoding='utf-8')
        return {**stats, 'validation_rc': result['rc'], 'status': status}


def new_row(sub, case, model):
    return dict(student=sub, case=case, model=model, passed=0, failed=0, errors=0,
                skipped=0, tests=0, elapsed_s=0, agent_rc='', validation_rc='', status='', note='',
                function_status='', functional_fraction=0.0, process_status='not_required',
                process_failures='', trace_valid=False, patch_valid=False, max_request_chars=0,
                suite_id='', suite_mode='', runner='local', validation_elapsed_s=0)


def evaluate(sub, case, out, model, rules, agent_timeout=AGENT_TIMEOUT,
             pytest_timeout=PYTEST_TIMEOUT, key_env=None):
    run_dir = out / f'{sub.name}__{case.name}'
    run_dir.mkdir()  # 必须是新目录，旧产物不能冒充本次结果。
    row = new_row(sub.name, case.name, model)
    cfg = rules
    row.update(suite_id='mini-agent-course', suite_mode='public')
    row.update(collect_usage(run_dir / 'run.log'))
    with tempfile.TemporaryDirectory(prefix='coding-eval-') as tmp:
        work_repo = Path(tmp) / 'repo'
        shutil.copytree(case / 'repo', work_repo, ignore=shutil.ignore_patterns(*IGNORED))
        task = Path(tmp) / 'task.md'
        shutil.copy2(case / 'task.md', task)
        before = snapshot(work_repo)
        result = run_agent(sub / 'agent.py', model, task, work_repo, run_dir, agent_timeout)
        reserved = list(result.get('unsafe_artifacts', []))
        for name in ('changes.json', 'repo_after', 'pytest_output.txt', 'junit.xml',
                     'validation_baseline_output.txt',
                     'evidence.json', 'patch_check.txt', 'result.json'):
            path = run_dir / name
            if path.exists() or path.is_symlink():
                reserved.append('reserved_artifact:' + name)
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        row.update(agent_rc=result['rc'], elapsed_s=round(result['elapsed_s'], 3))
        row.update(collect_usage(run_dir / 'run.log'))
        after = snapshot(work_repo)
        changes = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        (run_dir / 'changes.json').write_text(json.dumps(changes, ensure_ascii=False, indent=2), encoding='utf-8')
        shutil.copytree(work_repo, run_dir / 'repo_after', symlinks=True, ignore=shutil.ignore_patterns(*IGNORED))
        symlinks = [str(p.relative_to(work_repo)) for p in work_repo.rglob('*') if p.is_symlink()]
        # 即使 agent 退出失败也验证，保留部分正确性信息。
        validation_start = time.monotonic()
        if symlinks:
            row.update(status='invalid_submission', validation_rc='', note='symlink_in_repo')
        else:
            row.update(run_validation(case, work_repo, run_dir, pytest_timeout, key_env))
        row['validation_elapsed_s'] = round(time.monotonic() - validation_start, 3)
        row['function_status'] = row['status']
        # 超时或验证器异常时，部分 JUnit 记录不能代表完整验收。
        row['functional_fraction'] = (round(row['passed'] / row['tests'], 6)
            if row['tests'] and row['function_status'] not in {'validation_timeout', 'validation_error'} else 0.0)
        violations = reserved
        if symlinks:
            violations.append('symlink_in_repo:' + ','.join(symlinks))
        if result['rc'] != 0:
            violations.append('agent_timeout' if result['timeout'] else 'agent_failed')
        for name in ('run.log', 'patch.diff'):
            artifact = run_dir / name
            if artifact.is_symlink() or not artifact.is_file() or (name == 'run.log' and artifact.stat().st_size == 0):
                violations.append('missing_' + name)
        if cfg.get('editable') is not None:
            allowed = set(cfg['editable'])
            forbidden = [k for k in changes if k not in allowed]
        else:
            forbidden = [k for k in changes if k.startswith('test_') or Path(k).name in
                         {'conftest.py', 'pytest.ini', 'pyproject.toml', 'setup.cfg'}]
        if forbidden:
            violations.append('forbidden_changes:' + ','.join(forbidden))
        events, trace_errors = read_events(run_dir / 'run.log')
        row['trace_valid'] = not trace_errors
        if trace_errors:
            violations.extend(trace_errors)
        row['patch_valid'] = not symlinks and check_patch(before, after, run_dir / 'patch.diff', run_dir)
        if not row['patch_valid']:
            violations.append('patch_mismatch')
        evidence = inspect_process(events, cfg.get('process', {}))
        manual_review = []
        if cfg.get('process', {}).get('min_plan_items'):
            manual_review.append('核对计划内容、状态和可见记录是否与真实执行一致')
        evidence['manual_review'] = manual_review
        row.update(max_request_chars=evidence['max_request_chars'],
                   process_status=('passed' if evidence['passed'] else 'failed') if cfg.get('process') else 'not_required',
                   process_failures=';'.join(evidence['failed_checks']), manual_review=';'.join(manual_review))
        (run_dir / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        if row['status'] == 'passed' and not evidence['passed']:
            row.update(status='process_failed', note=row['process_failures'])
        if violations:
            row['note'] = ';'.join(violations)
            # 验证异常尚未得出可靠成绩，不能用入口错误覆盖验证状态并计零。
            if row['function_status'] in {'validation_timeout', 'validation_error'}:
                row['status'] = row['function_status']
            else:
                row['status'] = 'agent_timeout' if result['timeout'] else 'invalid_submission'
            row['functional_fraction'] = 0.0
        (run_dir / 'result.json').write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
    return row
