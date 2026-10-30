"""确定性的诊断选择：仅使用实际工具观察，无额外模型调用。全部计入核心行数。"""
import json
import re


class DiagnosticContext:
    def __init__(self, log):
        self.log = log
        self.records = {}
        self.serial = 0

    def observe(self, action, result):
        self.serial += 1
        tool = (action or {}).get('tool', 'invalid')
        path = (action or {}).get('path', '')
        key = (tool, path or str((action or {}).get('argv', '')))
        record = {'id': self.serial, 'tool': tool, 'path': path,
                  'action': action, 'result': result}
        if tool == 'write' and 'error' not in result and 'denied' not in result:
            self.records.pop(('read', path), None)
        self.records[key] = record

    def build(self, prefix, limit, state):
        if sum(len(m['content']) for m in prefix) > limit:
            raise ValueError('固定上下文超过预算')
        commands = [r for r in self.records.values() if r['tool'] == 'command']
        latest_write = max((r['id'] for r in self.records.values()
                            if r['tool'] == 'write'), default=0)
        active = [r for r in commands if r['id'] > latest_write]
        failed = [r for r in active if r['result'].get('rc', 0) != 0]
        phase = ('repair' if failed else 'verify' if latest_write and state['latest_test'] is None
                 else 'finish' if state['latest_test'] == 0 else 'explore')
        evidence = '\n'.join(json.dumps(r['result'], ensure_ascii=False) for r in failed)
        anchors = set(re.findall(r'[\w./-]+\.py|test_\w+|[A-Za-z_]\w*Error', evidence))
        ranked = []
        for r in self.records.values():
            score = r['id'] / max(1, self.serial)
            reasons = ['recency']
            if r in active:
                score += 8
                reasons.append('current_validation')
            if r in failed:
                score += 4
                reasons.append('failure')
            if r['path'] and any(r['path'].endswith(a) for a in anchors):
                score += 6
                reasons.append('diagnostic_path')
            if r['tool'] == 'write':
                score += 5
                reasons.append('latest_code')
            if r['tool'] == 'read':
                score += 2
                reasons.append('source')
            ranked.append((score, r, reasons))
        ranked.sort(key=lambda x: (-x[0], -x[1]['id']))
        focus = '诊断选择状态：' + json.dumps({'phase': phase, 'anchors': sorted(anchors)}, ensure_ascii=False)
        remaining = limit - sum(len(m['content']) for m in prefix)
        selected, audit = [], []
        for score, r, reasons in ranked:
            text = json.dumps(r, ensure_ascii=False)
            budget = min(4500, remaining - len(focus) - 30)
            if budget < 250:
                audit.append({'id': r['id'], 'score': score, 'reasons': reasons, 'selected': False})
                continue
            compressed = self.compress(r, text, budget)
            selected.append(compressed)
            remaining -= len(compressed) + 2
            audit.append({'id': r['id'], 'score': score, 'reasons': reasons,
                          'selected': True, 'before_chars': len(text), 'after_chars': len(compressed)})
        content = focus + '\n\n' + '\n\n'.join(selected)
        messages = prefix + [{'role': 'user', 'content': content}] if len(content) <= limit - sum(len(m['content']) for m in prefix) else prefix
        self.log('context_summary', method='diagnostic_selection', reason='按执行反馈选择',
                 phase=phase, candidates=audit, before_chars=sum(len(json.dumps(r, ensure_ascii=False))
                 for r in self.records.values()), after_chars=sum(len(m['content']) for m in messages),
                 retained=messages, discarded_ids=[a['id'] for a in audit if not a['selected']])
        return messages

    @staticmethod
    def compress(record, text, budget):
        if len(text) <= budget:
            return text
        if record['tool'] == 'command':
            result = record['result']
            lines = (result.get('stdout', '') + '\n' + result.get('stderr', '')).splitlines()
            pattern = r'FAILED|Error|assert|Expected|Obtained|\.py:\d+|mismatch|expected|actual|passed|failed'
            hits = [i for i, line in enumerate(lines) if re.search(pattern, line, re.I)]
            indices = sorted({j for i in hits for j in range(max(0, i-1), min(len(lines), i+2))})
            unique = list(dict.fromkeys(lines[i] for i in indices))
            excerpt = '\n'.join(unique)
            header = json.dumps({'id': record['id'], 'argv': record['action'].get('argv'),
                                 'rc': result.get('rc'), 'diagnostic_lines': len(unique)}, ensure_ascii=False)
            text = header + '\n' + (excerpt if excerpt else text)
        half = (budget - 45) // 2
        return text[:half] + '\n[诊断摘录/中段省略，完整原文见日志]\n' + text[-half:]
