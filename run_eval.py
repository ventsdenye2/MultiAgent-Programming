#!/usr/bin/env python3
"""依次运行全部五道公开题，保存逐题结果并汇总五分制成绩。"""
import argparse
import csv
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'tools'))
from contracts import submission_config_error
from evaluator import AGENT_TIMEOUT, PYTEST_TIMEOUT, check_environment, evaluate, new_row

CASES = ('case01_bug_fix', 'case02_feature_regression', 'case03_cross_file',
         'case04_two_subtasks', 'case05_long_log')
PENDING = {'validation_error', 'validation_timeout', 'evaluator_error'}


def atomic_write(path, content):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(content, encoding='utf-8')
    temporary.replace(path)


def case_verdict(status):
    if status == 'passed':
        return '通过'
    return '待复测' if status in PENDING else '未通过'


def overall_verdict(report):
    rows = report['results']
    passed = sum(row['status'] == 'passed' for row in rows)
    if report['complete']:
        label = '全部通过' if passed == len(CASES) else '未全部通过'
        return f'【{label}】已通过 {passed}/5 题；未通过 {len(CASES) - passed} 题。'
    pending = sum(row['status'] in PENDING for row in rows)
    failed = len(rows) - passed - pending
    return (f'【评测未完成】已通过 {passed}/5 题；未通过 {failed} 题；'
            f'待复测 {pending} 题；尚未评测 {len(CASES) - len(rows)} 题。总分暂不判定。')


def save_summary(out, rows, model):
    """每题结束即保存；验证异常或中断时，不发布不完整的五题总分。"""
    complete = len(rows) == len(CASES) and all(r['status'] not in PENDING for r in rows)
    points = sum(r['points'] or 0 for r in rows) if complete else None
    report = {'model': model, 'cases': list(CASES), 'evaluated_cases': len(rows),
              'complete': complete, 'total_score': points, 'max_score': 5, 'results': rows}
    atomic_write(out / 'summary.json', json.dumps(report, ensure_ascii=False, indent=2))
    stream = io.StringIO(newline='')
    fields = list(dict.fromkeys(k for row in rows for k in row)) or ['case', 'status', 'points']
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    atomic_write(out / 'summary.csv', stream.getvalue())
    score = '待完成评测' if points is None else f'{points}/5'
    lines = ['# 公开题自测结果', '', f'**{overall_verdict(report)}**', '', f'五题总分：**{score}**。', '',
             '| 题目 | 结论 | 详细状态 | 得分 | 测试通过/总数 | 产物 |',
             '| --- | --- | --- | ---: | ---: | --- |']
    for row in rows:
        value = '待复测' if row['points'] is None else str(row['points'])
        artifact = row['artifact_dir']
        lines.append(f"| {row['case']} | **{case_verdict(row['status'])}** | {row['status']} | {value} | "
                     f"{row['passed']}/{row['tests']} | [结果]({artifact}/result.json) |")
    lines += ['', '每题只有 passed 得1分，其他已完成状态得0分。验证异常不记为0分，排查后换新目录重测。',
              '逐题 result.json 中的 note、process_failures 和 manual_review 可帮助定位问题。',
              '此结果只核对可见的测试与过程记录；交互演示、特色实验和报告须按课程要求完成，轨迹真实性须结合实际运行核对。', '']
    atomic_write(out / 'summary.md', '\n'.join(lines))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent', required=True, type=Path, help='自己提交目录中的 agent.py 路径')
    parser.add_argument('--out', required=True, type=Path, help='全新的结果目录；已存在时拒绝覆盖')
    parser.add_argument('--model', help='可选，须与入口同目录 config.json 的 model 一致；默认读取配置')
    parser.add_argument('--agent-timeout', type=float, default=AGENT_TIMEOUT, help='每题 agent 秒数，默认600')
    parser.add_argument('--pytest-timeout', type=float, default=PYTEST_TIMEOUT, help='每题最终验证秒数，默认120')
    args = parser.parse_args(argv)
    agent, out = args.agent.resolve(), args.out.resolve()
    try:
        if not agent.is_file() or agent.name != 'agent.py':
            raise ValueError('--agent 必须指向自己的 agent.py 文件')
        for limit in (args.agent_timeout, args.pytest_timeout):
            if not math.isfinite(limit) or limit <= 0:
                raise ValueError('超时时间必须是有限正数')
        if args.out.exists() or args.out.is_symlink():
            raise ValueError('--out 已存在；请使用新的目录名，保留上一轮结果')
        tasks = ROOT / '公开任务'
        if out.is_relative_to(tasks) or tasks.is_relative_to(out) or agent.is_relative_to(out):
            raise ValueError('--out 不能覆盖原始任务、课程目录或自己的入口目录')
        config = json.loads(agent.with_name('config.json').read_text(encoding='utf-8'))
        problem = submission_config_error(config)
        if problem:
            raise ValueError('config.json 不符合课程约定：' + problem)
        model = config['model']
        if args.model is not None and args.model != model:
            raise ValueError('--model 必须与 config.json 的 model 一致')
        if not os.environ.get(config['key_env']):
            raise ValueError('请在当前终端设置 config.json 的 key_env 指定的密钥环境变量')
        rules = json.loads((ROOT / 'tools/public_rules.json').read_text(encoding='utf-8'))
        if set(rules) != set(CASES):
            raise ValueError('public_rules.json 必须包含课程的五道公开题')
        for name in CASES:
            case = tasks / name
            if not (case / 'task.md').is_file() or not any((case / 'repo').rglob('test_*.py')):
                raise ValueError('题目不完整：' + name)
        check_environment()
        out.mkdir(parents=True, exist_ok=False)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    rows = []
    save_summary(out, rows, model)
    try:
        for name in CASES:
            case = tasks / name
            artifact = f'{agent.parent.name}__{name}'
            print(f'开始 {name}；agent 上限 {args.agent_timeout:g}秒；产物：{out / artifact}', flush=True)
            try:
                row = evaluate(agent.parent, case, out, model, rules[name],
                               args.agent_timeout, args.pytest_timeout, key_env=config['key_env'])
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
                row = new_row(agent.parent.name, name, model)
                row.update(status='evaluator_error', note=f'{type(exc).__name__}: {exc}')
            row.update(points=None if row['status'] in PENDING else int(row['status'] == 'passed'),
                       artifact_dir=artifact)
            run_dir = out / artifact
            run_dir.mkdir(exist_ok=True)
            atomic_write(run_dir / 'result.json', json.dumps(row, ensure_ascii=False, indent=2))
            rows.append(row)
            report = save_summary(out, rows, model)
            print(f"结束 {name}：【{case_verdict(row['status'])}】（{row['status']}）；"
                  f"通过 {row['passed']}/{row['tests']} 个测试；"
                  f"得分 {'待复测' if row['points'] is None else row['points']}", flush=True)
    except KeyboardInterrupt:
        report = save_summary(out, rows, model)
        print('\n' + overall_verdict(report), file=sys.stderr, flush=True)
        print(f'已中断；保留已完成结果：{out}。重测时使用新的 --out。', file=sys.stderr)
        return 130
    print('\n' + overall_verdict(report), flush=True)
    print(f"五题总分：{str(report['total_score']) + '/5' if report['complete'] else '待复测'}；"
          f"汇总：{out / 'summary.md'}", flush=True)
    if not report['complete']:
        return 2
    return 0 if all(row['status'] == 'passed' for row in rows) else 1


if __name__ == '__main__':
    sys.exit(main())
