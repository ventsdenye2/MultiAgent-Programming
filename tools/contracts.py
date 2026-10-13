"""课程轨迹协议与过程证据检查；只检查可见记录，不证明日志真实性。"""
import ast
import json
from pathlib import Path
from posixpath import normpath
import re
from urllib.parse import urlsplit

MODEL_PROVIDERS = {'deepseek-v4-flash': 'deepseek', 'deepseek-flash': 'deepseek',
                   'qwen3.8-flash': 'qwen'}
ALLOWED_MODELS = set(MODEL_PROVIDERS)


def submission_config_error(config):
    """检查必填接入配置；不调用 API，也不读取或输出密钥。"""
    if not isinstance(config, dict):
        return 'invalid_config'
    model = config.get('model')
    if not isinstance(model, str) or model not in ALLOWED_MODELS:
        return 'invalid_model'
    base = config.get('base_url')
    if not isinstance(base, str) or not base or re.search(r'\s', base):
        return 'invalid_base_url'
    try:
        parsed = urlsplit(base)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
            return 'invalid_base_url'
    except ValueError:
        return 'invalid_base_url'
    key_env = config.get('key_env')
    if not isinstance(key_env, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key_env):
        return 'invalid_key_env'
    return ''


def valid_argv(argv):
    return isinstance(argv, list) and bool(argv) and all(isinstance(arg, str) and arg for arg in argv)


def tool_error(result):
    return isinstance(result, dict) and (bool(result.get('error')) or
                                       result.get('ok') is False or result.get('success') is False)


def valid_message(message, request=False):
    if not isinstance(message, dict):
        return False
    if request and (not isinstance(message.get('role'), str) or not message['role'].strip()):
        return False
    return (isinstance(message.get('content'), (str, list)) or
            bool(message.get('tool_calls')) or bool(message.get('function_call')))


def request_messages(event):
    """优先采用符合日志协议的真实 messages；其他 API 使用外层映射。"""
    body = event.get('body')
    messages = body.get('messages') if isinstance(body, dict) else None
    if isinstance(messages, list) and messages and all(valid_message(m, True) for m in messages):
        return messages
    return event.get('messages')


def response_payload(event):
    return json.loads(event['raw']) if 'raw' in event else event.get('response')


def read_events(path):
    events, errors = [], []
    if path.is_symlink():
        return [], ['symlink_log']
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError):
        return [], ['missing_or_unreadable_log']
    for number, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
            if not isinstance(event, dict) or not isinstance(event.get('event'), str):
                raise ValueError('invalid event')
            events.append(event)
        except (ValueError, TypeError):
            errors.append(f'invalid_jsonl_line:{number}')
    requests = sum(e['event'] == 'model_request' for e in events)
    responses = sum(e['event'] == 'model_response' for e in events)
    failures = sum(e['event'] == 'model_error' for e in events)
    if not requests or not responses or requests != responses + failures:
        errors.append('missing_or_unbalanced_model_trace')
    pending = 0
    for event in events:
        if event['event'] == 'model_request':
            pending += 1
            body = event.get('body')
            messages = request_messages(event)
            if (not isinstance(body, dict) or not body or not isinstance(messages, list) or
                not messages or not all(valid_message(message, True) for message in messages)):
                errors.append('missing_request_messages')
        if event['event'] in {'model_response', 'model_error'}:
            if pending:
                pending -= 1
            else:
                errors.append('unmatched_model_response')
        if event['event'] == 'model_response':
            try:
                payload = response_payload(event)
                if not isinstance(payload, (dict, list)) or not payload:
                    raise ValueError('invalid response')
            except (ValueError, TypeError):
                errors.append('missing_response_payload')
        wrapped = event['event'] in {'tool_result', 'verification'}
        result = event.get('result') if wrapped else event
        action = event.get('action') if wrapped else event
        if wrapped and not isinstance(action, dict):
            if not tool_error(result):
                errors.append('invalid_tool_action')
            continue
        name = action.get('tool') if wrapped else {'file_read': 'read', 'file_write': 'write'}.get(event['event'])
        if tool_error(result) and (not isinstance(result, dict) or 'rc' not in result):
            continue  # 工具启动/参数错误是合法失败记录，不是已执行成功的动作。
        if event['event'] == 'command_result' or (event['event'] == 'tool_result' and
                name == 'command') or event['event'] == 'verification':
            if (not valid_argv(action.get('argv')) or not isinstance(result, dict) or
                type(result.get('rc')) is not int or not all(
                    isinstance(result.get(k), str) for k in ('stdout', 'stderr'))):
                errors.append('invalid_command_result')
        elif name in {'read', 'write'}:
            content = action.get('content') if wrapped and name == 'write' else result.get('content') if isinstance(result, dict) else None
            if not isinstance(action.get('path'), str) or not action['path'] or not isinstance(content, str):
                errors.append('incomplete_file_' + name)
    if not any(e['event'] in {'tool_result', 'command_result', 'file_write', 'file_read'} for e in events):
        errors.append('missing_tool_trace')
    return events, sorted(set(errors))


def actions(events):
    for index, event in enumerate(events):
        if event['event'] in {'tool_result', 'verification'} and isinstance(event.get('action'), dict):
            yield index, event['action'], event.get('result', {})
        elif event['event'] == 'command_result':
            yield index, {'tool': 'command', 'argv': event.get('argv')}, event
        elif event['event'] in {'file_read', 'file_write'}:
            yield index, {'tool': event['event'][5:], 'path': event.get('path'),
                          'content': event.get('content')}, event
        elif event['event'] == 'plan':
            yield index, {'tool': 'plan', 'items': event.get('items')}, event


def is_pytest(argv):
    if not valid_argv(argv):
        return False
    executable = Path(argv[0]).name
    args = argv[1:]
    if executable.startswith('python') and args[:2] == ['-m', 'pytest']:
        args = args[2:]
    elif executable not in {'pytest', 'pytest.exe'}:
        return False
    blocked = {'--collect-only', '--co', '--lf', '--last-failed', '--sw', '--stepwise',
               '--stepwise-skip', '--deselect', '--ignore', '--ignore-glob', '--pyargs',
               '--keyword', '--markexpr', '-c', '-o', '--override-ini'}
    valued = {'--tb', '--color', '--capture', '--junitxml', '--junit-xml', '--junitprefix',
              '--junit-prefix', '--basetemp', '--durations', '--durations-min', '--maxfail',
              '--import-mode', '--assert', '--log-level', '--log-file', '--log-file-level',
              '--log-format', '--log-date-format', '-r'}
    index = 0
    while index < len(args):
        arg = args[index]
        if arg.split('=', 1)[0] in blocked or arg.startswith(('-k', '-m')):
            return False
        if arg in valued:
            index += 1
            if index == len(args):
                return False
        elif not arg.startswith('-') and arg not in {'.', './'}:
            return False  # 指定文件、node ID、子目录都会缩小测试范围。
        index += 1
    return True


def is_diagnostic(argv, script):
    if not valid_argv(argv):
        return False
    if Path(argv[0]).name == script:
        return True
    if not Path(argv[0]).name.startswith('python'):
        return False
    args = argv[1:]
    while args and args[0] in {'-B', '-u', '-I', '-E', '-s'}:
        args = args[1:]
    return bool(args and (Path(args[0]).name == script or args[:2] == ['-m', Path(script).stem]))


def defines_symbol(content, symbol):
    """从完整写入内容识别函数或变量的定义；注释和字符串不算定义。"""
    if not isinstance(content, str):
        return None
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return None
    return any((isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.name == symbol) or
               (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == symbol) or
               (isinstance(node, ast.alias) and (node.asname or node.name) == symbol)
               for node in ast.walk(tree))


def first_subtask_passed(result, rule):
    """完整 pytest 汇总列全失败项；总数一致且首项测试不在其中，才算中间验证成功。"""
    output = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', result['stdout'] + result['stderr'])
    summaries = re.findall(r'^(?:=+\s*)?(\d+ \w+(?:, \d+ \w+)*) in [\d.]+s\b.*$', output, re.M)
    if not summaries or result['rc'] != 1:
        return False
    counts = {name: int(count) for count, name in re.findall(r'(\d+) (\w+)', summaries[-1])}
    failed = re.findall(r'^FAILED (.+?)(?: - |$)', output, re.M)
    return (set(counts) <= {'passed', 'failed', 'warning', 'warnings'}
            and counts.get('passed', 0) >= len(rule['first_tests'])
            and counts.get('passed', 0) + counts.get('failed', 0) == rule['test_count']
            and len(set(failed)) == counts.get('failed', 0)
            and not any(node.endswith(test) for node in failed for test in rule['first_tests']))


def inspect_subtask_order(records, commands, plans, rule, valid_plan):
    writes = [(i, defines_symbol(a.get('content'), rule['second_symbol']))
              for i, a, r in records if a.get('tool') == 'write' and not tool_error(r)
              and isinstance(a.get('path'), str) and Path(a['path']).name == rule['file']]
    second = next((i for i, defined in writes if defined is True), -1)
    prior = [(i, defined) for i, defined in writes if i < second]
    separate = bool(prior and prior[-1][1] is False)
    middle = [i for i, argv, r in commands if separate and prior[-1][0] < i < second
              and is_pytest(argv) and first_subtask_passed(r, rule)]
    initial = [items for i, items in plans if writes and i < writes[0][0] and valid_plan(items)
               and items[0]['status'] != 'done' and items[1]['status'] != 'done']
    updated = any(test < i < second and valid_plan(items) and items[0]['status'] == 'done'
                  and items[1]['status'] != 'done'
                  and any([item['title'] for item in items[:2]] ==
                          [item['title'] for item in start[:2]] for start in initial)
                  for test in middle for i, items in plans)
    return {'separate_subtask_writes': separate,
            'net_verified_before_csv': bool(middle), 'plan_updated_before_csv': updated}


def inspect_process(events, requirements):
    records = [(i, a, r) for i, a, r in actions(events) if isinstance(a, dict)]
    writes = [i for i, a, r in records if a.get('tool') == 'write' and not tool_error(r)]
    first, last = min(writes, default=-1), max(writes, default=-1)
    commands = [(i, a.get('argv'), r) for i, a, r in records
                if a.get('tool') == 'command' and isinstance(r, dict) and type(r.get('rc')) is int
                and valid_argv(a.get('argv')) and all(isinstance(r.get(k), str) for k in ('stdout', 'stderr'))]
    plans = [(i, a.get('items')) for i, a, r in records if a.get('tool') == 'plan' and not tool_error(r)]
    checks = {}
    if requirements:
        checks['observable_write'] = bool(writes)
    if requirements.get('baseline_test'):
        checks['baseline_test'] = any(i < first and is_pytest(argv) and r.get('rc') in (1, 2)
            and re.search(r'\d+\s+(?:failed|errors?)\b', r.get('stdout', '') + r.get('stderr', ''), re.I)
            for i, argv, r in commands)
    if requirements.get('post_tests'):
        checks['post_tests'] = any(i > last >= 0 and is_pytest(argv) and r.get('rc') == 0
            and re.search(r'\d+ passed', r.get('stdout', '')) for i, argv, r in commands)
    min_plan = requirements.get('min_plan_items', 0)
    if min_plan:
        valid = lambda items: isinstance(items, list) and len(items) >= min_plan and all(
            isinstance(x, dict) and isinstance(x.get('title'), str) and x['title'].strip()
            and x.get('status') in {'todo', 'doing', 'done'} for x in items)
        checks['plan_before_write'] = any(i < first and valid(items) for i, items in plans)
        checks['final_plan_done'] = bool(plans and plans[-1][0] > last >= 0 and valid(plans[-1][1]) and all(
            item['status'] == 'done' for item in plans[-1][1]))
        if requirements.get('subtask_order'):
            checks.update(inspect_subtask_order(records, commands, plans, requirements['subtask_order'], valid))
    if requirements.get('min_read_files'):
        paths = {normpath(a['path']) for i, a, r in records if i < first and a.get('tool') == 'read'
                 and isinstance(a.get('path'), str) and a['path'].endswith('.py')
                 and not Path(a['path']).name.startswith('test_')
                 and isinstance(r, dict) and not tool_error(r) and isinstance(r.get('content'), str)}
        checks['cross_file_reads'] = len(paths) >= requirements['min_read_files']
    diagnostic = requirements.get('diagnostic')
    if diagnostic:
        diagnostics = [(i, r) for i, argv, r in commands if is_diagnostic(argv, diagnostic)]
        checks['long_diagnostic_before_write'] = any(i < first and r.get('rc') != 0 and
            len(r.get('stdout', '') + r.get('stderr', '')) >= requirements.get('min_diagnostic_chars', 0)
            for i, r in diagnostics)
        checks['diagnostic_after_write'] = any(i > last >= 0 and r.get('rc') == 0 for i, r in diagnostics)
        checks['context_strategy_event'] = any(e['event'] in {'context_clip', 'context_drop', 'context_summary'}
                                               for e in events)
    sizes = []
    for event in events:
        messages = request_messages(event)
        if event['event'] == 'model_request' and isinstance(messages, list):
            sizes.append(sum(len(m.get('content', '')) if isinstance(m.get('content'), str)
                             else len(json.dumps(m.get('content'), ensure_ascii=False))
                             for m in messages if isinstance(m, dict)))
    maximum = max(sizes, default=0)
    if requirements.get('context_chars'):
        checks['context_budget'] = bool(sizes) and maximum <= requirements['context_chars']
    return {'checks': checks, 'passed': all(checks.values()),
            'failed_checks': [k for k, passed in checks.items() if not passed],
            'max_request_chars': maximum}
