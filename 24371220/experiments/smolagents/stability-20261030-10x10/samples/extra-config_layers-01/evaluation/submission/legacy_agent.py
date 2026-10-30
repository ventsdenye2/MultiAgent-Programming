"""命令行迷你编码智能体，核心范围为 SYSTEM 和 Agent。"""
import argparse
import json
from pathlib import Path
import re
import sys
from runtime import Runtime
from context_selection import DiagnosticContext
import os

SYSTEM = '''你是编码智能体。理解任务并通过工具修改业务文件，禁止修改测试、诊断和任务。
每轮只返回一个 JSON 对象，不要 markdown，不要一次多个动作。
工具协议：
{"tool":"list"} 列出仓库文件。
{"tool":"read","path":"相对路径"} 完整读文件。
{"tool":"write","path":"允许的业务文件","content":"完整新内容"} 写文件。
{"tool":"command","argv":["python","-m","pytest","-q"]} 运行完整测试。
{"tool":"command","argv":["python","run_checks.py"]} 运行题目诊断。
{"tool":"plan","items":[{"title":"子目标","status":"doing"}]} 更新完整计划。
{"tool":"finish","summary":"完成说明"} 结束，失败测试不得宣称成功。
必须先建计划，再执行；计划标题和顺序保持不变，只更新 todo/doing/done。
修改前后都运行完整 pytest。首次写入前完整阅读至少两个业务文件（若只有一个则读一个）。
仅当题面要求净额和 CSV 两个子任务时：仅修净额，跑完整测试核对净额通过，第一项置 done，才实现 CSV。
这类题尚未实现 CSV 时的中间测试失败正常，不能因此跳过步骤。其他题不要添加净额/CSV 目标。
先用 list 判断是否有 run_checks.py，仅有该文件时修改前后运行它，无此文件不要调用。
阅读输出定位共同根因，写入最小必要修复，不能硬编码测试答案。
工具结果可能被裁剪，完整原文已写入日志。历史删除后依据题面和当前计划继续。
命令只支持上述两种，无 shell 或删除工具。所有文件路径限定在仓库内。
'''


class Agent:
    def __init__(self, runtime, task, auto):
        self.rt = runtime
        self.auto = auto
        self.plan = []
        self.history = []
        self.selector = DiagnosticContext(runtime.log) if runtime.config.get('context_mode', 'baseline') == 'diagnostic' else None
        self.task = task
        self.reads = set()
        self.writes = 0
        self.baseline = False
        self.diagnostic_before = False
        self.last_test = None
        self.last_diagnostic = None
        self.limit = min(16000, runtime.config.get('context_chars', 15000))
        if self.limit < 8000:
            raise ValueError('context_chars 至少为 8000')
        self.fixed = [{'role': 'system', 'content': SYSTEM},
                      {'role': 'user', 'content': task}]
        if self.size(self.fixed) > self.limit - 2000:
            raise ValueError('题面过长，无法保留完整任务')
        self.business = {p for p in runtime.editable if p.endswith('.py')}
        self.has_diagnostic = (runtime.repo / 'run_checks.py').is_file()

    @staticmethod
    def size(messages):
        return sum(len(m['content']) for m in messages)

    def clip(self, text, budget=4500):
        if len(text) <= budget:
            return text
        half = (budget - 80) // 2
        kept = text[:half] + '\n[中段已裁剪；完整内容见 run.log]\n' + text[-half:]
        self.rt.log('context_clip', method='head_tail', reason='单条结果过长',
                    before_chars=len(text), after_chars=len(kept),
                    retained=kept, discarded=text[half:-half])
        return kept

    def messages(self):
        state = {'role': 'user', 'content': '当前计划与执行状态：' + json.dumps({
            'items': self.plan, 'writes': self.writes, 'baseline': self.baseline,
            'read_files': sorted(self.reads), 'latest_test': self.last_test,
            'diagnostic': self.last_diagnostic}, ensure_ascii=False)}
        prefix = self.fixed + [state]
        if self.selector:
            return self.selector.build(prefix, self.limit, {'latest_test': self.last_test})
        while self.history and self.size(prefix + self.history) > self.limit:
            removed = self.history[:2]
            self.history = self.history[2:]
            self.rt.log('context_drop', method='sliding_window', reason='请求超过字符预算',
                        before_chars=self.size(prefix + removed + self.history),
                        after_chars=self.size(prefix + self.history), discarded=removed,
                        retained=prefix + self.history)
        if self.size(prefix) > self.limit:
            raise ValueError('任务和计划超过上下文预算')
        return prefix + self.history

    def progress(self):
        for item in self.plan:
            print(f"[{item['status']}] {item['title']}")
        if not self.plan:
            print('尚未建立计划')

    def interact(self, action=None):
        while True:
            prompt = '回车继续，/status 查看，/add 指令，/quit 中断'
            if action:
                display = dict(action)
                if 'content' in display:
                    display['content'] = f"完整写入 {len(action['content'])} 字符"
                print(json.dumps(display, ensure_ascii=False))
                if action['tool'] == 'write':
                    print(action['content'])
                prompt = '输入 y 确认，n 拒绝；/status、/add 指令、/quit'
            answer = input(prompt + '> ').strip()
            if answer == '/quit':
                raise KeyboardInterrupt
            if answer == '/status':
                self.progress()
                continue
            if answer.startswith('/add '):
                content = answer[5:].strip()
                self.rt.log('user_instruction', content=content)
                self.fixed.append({'role': 'user', 'content': content})
                if action:
                    return False
                continue
            if action:
                if answer.lower() in ('y', 'n'):
                    return answer.lower() == 'y'
            elif not answer:
                return True
            else:
                self.rt.log('user_instruction', content=answer)
                self.fixed.append({'role': 'user', 'content': answer})

    def update_plan(self, items):
        if not isinstance(items, list) or not 1 <= len(items) <= 10:
            raise ValueError('计划必须有 1 至 10 项')
        for item in items:
            if not isinstance(item.get('title'), str) or not item['title'].strip():
                raise ValueError('计划标题不能为空')
            if item.get('status') not in ('todo', 'doing', 'done'):
                raise ValueError('计划状态无效')
        if self.plan and [i['title'] for i in items] != [i['title'] for i in self.plan]:
            raise ValueError('计划标题和顺序须保持一致')
        self.plan = items
        self.rt.log('plan', items=items)
        self.progress()
        return {'items': items}

    def execute(self, action):
        tool = action['tool']
        if tool in ('write', 'command') and not self.auto:
            if not self.interact(action):
                return {'denied': True, 'message': '用户拒绝或追加指令，请重新规划动作'}
        if tool == 'list':
            return {'files': sorted(str(p.relative_to(self.rt.repo))
                    for p in self.rt.repo.rglob('*') if p.is_file()
                    and not any(part.startswith('.') for part in p.relative_to(self.rt.repo).parts))}
        if tool == 'read':
            result = self.rt.read(action['path'])
            self.reads.add(action['path'])
            return result
        if tool == 'plan':
            return self.update_plan(action['items'])
        if tool == 'write':
            if not self.baseline or not self.plan:
                raise ValueError('写入前必须建立计划并运行基线完整测试')
            if len(self.reads & self.business) < min(2, len(self.business)):
                raise ValueError('写入前须完整阅读至少两个业务文件，单文件题读一个')
            if self.has_diagnostic and not self.diagnostic_before:
                raise ValueError('写入前须运行 run_checks.py')
            result = self.rt.write(action['path'], action['content'])
            self.writes += 1
            self.last_test = None
            self.last_diagnostic = None
            return result
        if tool == 'command':
            result = self.rt.command(action['argv'])
            if action['argv'] == ['python', '-m', 'pytest', '-q']:
                if not self.writes:
                    self.baseline = True
                self.last_test = result['rc']
            else:
                if not self.writes:
                    self.diagnostic_before = True
                self.last_diagnostic = result['rc']
            return result
        if tool == 'finish':
            if not self.writes or self.last_test != 0:
                raise ValueError('尚未修改或修改后的完整测试未通过')
            if self.has_diagnostic and self.last_diagnostic != 0:
                raise ValueError('修改后的诊断未通过')
            if not self.plan or any(i['status'] != 'done' for i in self.plan):
                raise ValueError('所有子目标必须完成')
            self.rt.log('finish', summary=action.get('summary', ''))
            print(action.get('summary', '任务完成'))
            return {'finished': True}
        raise ValueError('未知工具')

    def run(self):
        for step in range(self.rt.config.get('max_steps', 60)):
            if not self.auto:
                self.interact()
            content = self.rt.request(self.messages())
            self.history.append({'role': 'assistant', 'content': self.clip(content or '')})
            action = None
            try:
                text = (content or '').strip()
                if text.startswith('```'):
                    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)
                action = json.loads(text)
                if not isinstance(action, dict):
                    raise ValueError('动作必须为 JSON 对象')
                print(f"步骤 {step + 1}: {action.get('tool', '无效动作')}")
                result = self.execute(action)
            except (ValueError, KeyError, OSError, TypeError) as exc:
                result = {'error': str(exc)}
                self.rt.log('tool_error', action=action, error=str(exc))
            if self.selector:
                self.selector.observe(action, result)
            self.history.append({'role': 'user', 'content': self.clip(
                json.dumps({'tool_result': result}, ensure_ascii=False))})
            if result.get('finished'):
                return 0
        self.rt.log('budget_exhausted', max_steps=self.rt.config.get('max_steps', 60))
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--auto', action='store_true')
    parser.add_argument('--context-mode', choices=['baseline', 'diagnostic'], default=None)
    parser.add_argument('--allow', nargs='+', help='题面无法提取时，明确指定允许修改的相对文件')
    args = parser.parse_args()
    config = json.loads(Path(__file__).with_name('config.json').read_text(encoding='utf-8'))
    config['context_mode'] = args.context_mode or os.environ.get('MINI_CONTEXT_MODE', 'baseline')
    if config['context_mode'] not in ('baseline', 'diagnostic'):
        parser.error('无效的上下文模式')
    if args.model != config['model']:
        parser.error('--model 必须与 config.json 一致')
    task = Path(args.task).read_text(encoding='utf-8')
    editable = args.allow or []
    if not editable:
        for line in task.splitlines():
            if '只修改' in line or '只允许修改' in line:
                editable.extend(re.findall(r'`([^`]+\.py)`', line))
    if not editable:
        parser.error('无法从题面提取允许修改的文件，请使用 --allow')
    rt = Runtime(args.repo, Path.cwd(), editable, config)
    rt.log('file_read', path=str(Path(args.task).resolve()), content=task)
    try:
        return Agent(rt, task, args.auto).run()
    except KeyboardInterrupt:
        rt.log('interrupted', reason='用户中断')
        return 130
    except Exception as exc:
        rt.log('error', error=str(exc))
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        rt.patch()


if __name__ == '__main__':
    sys.exit(main())
