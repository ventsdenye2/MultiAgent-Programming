#!/usr/bin/env python3
"""公开任务产物自检；可附入口退出码，轨迹真实性须结合实际运行核对。"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from contracts import inspect_process, read_events

IGNORED = {'__pycache__', '.pytest_cache', '.git'}


def prepare(case, attempt):
    rules = json.loads(Path(__file__).with_name('public_rules.json').read_text(encoding='utf-8'))
    if case not in rules:
        raise ValueError('只支持本目录的五道公开题；--case 填完整 case 名称')
    tasks = Path(__file__).resolve().parents[1] / '公开任务'
    source = tasks / case
    if not (source / 'task.md').is_file() or not (source / 'repo').is_dir():
        raise ValueError('缺少公开题源文件；请在完整课程材料中运行')
    if attempt.resolve().is_relative_to(tasks.resolve()):
        raise ValueError('本轮自测目录不能位于初始任务内')
    if attempt.exists() or attempt.is_symlink():
        raise ValueError('本轮目录已存在；请换新目录，避免覆盖结果或复用已修改的仓库')
    attempt.mkdir(parents=True, exist_ok=False)
    for name in ('before', 'work'):
        shutil.copytree(source, attempt / name, ignore=shutil.ignore_patterns(*IGNORED))
    (attempt / 'run').mkdir()
    return {'prepared': str(attempt), 'case': case, 'next': '在 run 目录启动自己的 agent；完成后用 --attempt 检查'}


def snapshot(folder):
    return {p.relative_to(folder).as_posix(): b'SYMLINK' if p.is_symlink() else p.read_bytes()
            for p in folder.rglob('*') if (p.is_file() or p.is_symlink()) and not set(p.parts) & IGNORED}


def check(case, before, repo, run_dir, agent_exit_code=None):
    rules = json.loads(Path(__file__).with_name('public_rules.json').read_text(encoding='utf-8'))
    if case not in rules:
        raise ValueError('只支持本目录的五道公开题；--case 填完整 case 名称')
    if not before.is_dir() or not repo.is_dir() or not run_dir.is_dir():
        raise ValueError('--before、--repo 和 --run-dir 必须是存在的目录')
    original, final = snapshot(before), snapshot(repo)
    changed = sorted(p for p in original.keys() | final.keys() if original.get(p) != final.get(p))
    events, errors = read_events(run_dir / 'run.log')
    process = inspect_process(events, rules[case]['process'])
    problems = list(errors)
    if agent_exit_code is not None and agent_exit_code != 0:
        problems.append(f'agent 非正常结束，退出码为 {agent_exit_code}')
    if any(p.is_symlink() for folder in (before, repo) for p in folder.rglob('*')):
        problems.append('仓库中含符号链接')
    if set(changed) - set(rules[case]['editable']):
        problems.append('修改了题面允许范围以外的文件')
    patch = run_dir / 'patch.diff'
    patch_ok = False
    if not patch.is_file() or patch.is_symlink():
        problems.append('补丁缺失或是符号链接')
    elif not shutil.which('patch'):
        raise ValueError('缺少 GNU patch；先配置课程环境')
    else:
        with tempfile.TemporaryDirectory(prefix='patch-check-') as tmp:
            restored = Path(tmp) / 'repo'
            restored.mkdir()
            for name, content in original.items():
                dest = restored / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
            applied = subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch.resolve())],
                                     cwd=restored, capture_output=True, timeout=30)
            patch_ok = applied.returncode == 0 and snapshot(restored) == final
        if not patch_ok:
            problems.append('补丁不能从初始仓库还原最终仓库')
    keys = [value.encode() for name, value in os.environ.items() if name.endswith('_API_KEY') and value]
    for path in (run_dir / 'run.log', patch):
        if path.is_file() and any(key in path.read_bytes() for key in keys):
            problems.append('产物中含环境变量密钥值')
    return {'ok': not problems and process['passed'], 'case': case, 'changed': changed,
            'agent_exit_code': agent_exit_code, 'patch_matches': patch_ok,
            'errors': sorted(set(problems)), 'process': process}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare', type=Path, help='在全新目录创建 before、work、run；不调用模型')
    mode.add_argument('--attempt', type=Path, help='检查 --prepare 创建的一轮工作副本')
    parser.add_argument('--agent-exit-code', type=int, help='附加核对启动 agent 后立即保存的退出码')
    for name in ('before', 'repo', 'run-dir'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args(argv)
    explicit = (args.before, args.repo, args.run_dir)
    if args.prepare is not None and args.agent_exit_code is not None:
        parser.error('--agent-exit-code 只用于检查，不能与 --prepare 一起使用')
    if (args.prepare is not None or args.attempt is not None) and any(p is not None for p in explicit):
        parser.error('--prepare/--attempt 不能与 --before、--repo、--run-dir 混用')
    if args.prepare is None and args.attempt is None and any(p is None for p in explicit):
        parser.error('请使用 --prepare、--attempt，或同时提供 --before、--repo、--run-dir')
    try:
        if args.prepare is not None:
            result = prepare(args.case, args.prepare)
        else:
            paths = ((args.attempt / 'before/repo', args.attempt / 'work/repo', args.attempt / 'run')
                     if args.attempt is not None else explicit)
            result = check(args.case, *paths, agent_exit_code=args.agent_exit_code)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print('【自检未完成】请根据下方错误检查参数、文件和环境，修正后重试。', file=sys.stderr, flush=True)
        parser.error(str(exc))
    if args.prepare is not None:
        message = f'【副本创建成功】{args.case}：接下来进入 run 目录启动智能体。'
    elif result['ok']:
        remaining = ('完整 pytest 测试全部通过' if args.agent_exit_code is not None else
                     'agent 正常退出且完整 pytest 测试全部通过')
        message = f'【产物自检通过】{args.case}：日志、补丁、修改范围和过程检查合格；仍需确认{remaining}。'
    else:
        message = f'【产物自检未通过】{args.case}：请查看下方 JSON 的 errors 和 process.failed_checks。'
    # 中文提示写到 stderr，stdout 保留完整 JSON，便于保存和解析。
    print(message, file=sys.stderr, flush=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if args.prepare is not None or result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
