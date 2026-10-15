"""基础机制单元测试；使用本地工具/模拟模型，不作为公开题成绩或模型轨迹。"""
import json
import sys
from pathlib import Path
import pytest
from agent import Agent
from runtime import Runtime


@pytest.fixture
def sample(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'calc.py').write_text('value = 1\n', encoding='utf-8')
    (repo / 'test_value.py').write_text('def test_value():\n    assert True\n', encoding='utf-8')
    out = tmp_path / 'run'
    out.mkdir()
    config = {'model': 'fake', 'base_url': 'https://example.invalid',
              'key_env': 'MINI_AGENT_TEST_KEY', 'max_steps': 10}
    rt = Runtime(repo, out, ['calc.py'], config)
    agent = Agent(rt, '只修改 `calc.py`', True)
    yield agent
    rt.patch()


def test_path_escape_and_test_write_blocked(sample):
    with pytest.raises(ValueError):
        sample.rt.read('../outside.txt')
    with pytest.raises(ValueError):
        sample.rt.write('test_value.py', 'changed')


def test_command_rejects_delete_and_filtered_tests(sample):
    for argv in [['rm', '-rf', '..'], ['python', '-c', 'print(1)'],
                 ['python', '-m', 'pytest', '-q', '-k', 'one']]:
        with pytest.raises(ValueError):
            sample.rt.command(argv)


def test_write_requires_baseline_plan_and_read(sample):
    action = {'tool': 'write', 'path': 'calc.py', 'content': 'value = 2\n'}
    with pytest.raises(ValueError):
        sample.execute(action)
    sample.update_plan([{'title': '修复', 'status': 'doing'}])
    sample.baseline = True
    with pytest.raises(ValueError):
        sample.execute(action)
    sample.execute({'tool': 'read', 'path': 'calc.py'})
    sample.execute(action)
    assert sample.writes == 1 and sample.last_test is None


def test_plan_titles_are_stable(sample):
    sample.update_plan([{'title': '修复', 'status': 'doing'}])
    with pytest.raises(ValueError):
        sample.update_plan([{'title': '改名', 'status': 'done'}])
    sample.update_plan([{'title': '修复', 'status': 'done'}])


def test_finish_requires_actual_post_test(sample):
    sample.writes = 1
    sample.update_plan([{'title': '修复', 'status': 'done'}])
    with pytest.raises(ValueError):
        sample.execute({'tool': 'finish'})
    sample.execute({'tool': 'command', 'argv': ['python', '-m', 'pytest', '-q']})
    assert sample.execute({'tool': 'finish'})['finished']


def test_long_result_keeps_full_log_and_bounded_request(sample):
    original = 'BEGIN\n' + 'x' * 20000 + '\nEND'
    sample.rt.log('command_result', argv=[sys.executable, 'run_checks.py'],
                  rc=1, stdout=original, stderr='')
    clipped = sample.clip(original)
    assert clipped.startswith('BEGIN') and clipped.endswith('END')
    for _ in range(8):
        sample.history.extend([{'role': 'assistant', 'content': '{"tool":"read"}'},
                               {'role': 'user', 'content': clipped}])
    assert sample.size(sample.messages()) <= 16000
    events = [json.loads(line) for line in (sample.rt.output / 'run.log').read_text().splitlines()]
    assert events[0]['stdout'] == original
    assert any(e['event'] == 'context_clip' for e in events)
    assert any(e['event'] == 'context_drop' for e in events)


def test_interaction_progress_append_and_refusal(sample, monkeypatch):
    answers = iter(['/status', '/add 保留接口'])
    monkeypatch.setattr('builtins.input', lambda _: next(answers))
    assert sample.interact({'tool': 'command', 'argv': ['python', '-m', 'pytest', '-q']}) is False
    assert sample.fixed[-1]['content'] == '保留接口'


def test_keyboard_interrupt(sample, monkeypatch):
    monkeypatch.setattr('builtins.input', lambda _: '/quit')
    with pytest.raises(KeyboardInterrupt):
        sample.interact()


def test_symlink_escape(sample, tmp_path):
    outside = tmp_path / 'outside.py'
    outside.write_text('secret')
    try:
        (sample.rt.repo / 'link.py').symlink_to(outside)
    except OSError:
        pytest.skip('当前系统不允许创建符号链接')
    with pytest.raises(ValueError):
        sample.rt.read('link.py')


def test_model_loop_invalid_action_then_finish(sample, monkeypatch):
    # 仅验证动作解析和循环，不生成任何伪造 model_request/model_response。
    sample.writes = 1
    sample.last_test = 0
    sample.update_plan([{'title': '修复', 'status': 'done'}])
    replies = iter(['not json', '{"tool":"finish","summary":"unit test"}'])
    monkeypatch.setattr(sample.rt, 'request', lambda _: next(replies))
    assert sample.run() == 0


def test_diagnostic_preserves_middle_failure_within_budget():
    from context_selection import DiagnosticContext
    events = []
    selector = DiagnosticContext(lambda event, **kw: events.append((event, kw)))
    output = 'noise\n' * 4000 + 'stats.py:42: AssertionError UNIQUE_ROOT_CAUSE\n' + 'noise\n' * 4000
    selector.observe({'tool': 'command', 'argv': ['python', '-m', 'pytest', '-q']},
                     {'rc': 1, 'stdout': output, 'stderr': ''})
    messages = selector.build([{'role': 'system', 'content': 'task'}], 8000, {'latest_test': 1})
    assert sum(len(m['content']) for m in messages) <= 8000
    assert 'UNIQUE_ROOT_CAUSE' in messages[-1]['content']
    assert events[-1][1]['phase'] == 'repair'


def test_diagnostic_drops_stale_source_and_resets_failure():
    from context_selection import DiagnosticContext
    events = []
    selector = DiagnosticContext(lambda event, **kw: events.append(kw))
    selector.observe({'tool': 'read', 'path': 'calc.py'}, {'content': 'OLD_CODE'})
    selector.observe({'tool': 'command', 'argv': ['python', '-m', 'pytest', '-q']},
                     {'rc': 1, 'stdout': 'calc.py:4: AssertionError', 'stderr': ''})
    selector.observe({'tool': 'write', 'path': 'calc.py', 'content': 'NEW_CODE'}, {'written': 'calc.py'})
    messages = selector.build([], 2000, {'latest_test': None})
    assert events[-1]['phase'] == 'verify'
    assert 'OLD_CODE' not in str(messages) and 'NEW_CODE' in str(messages)
    assert 'anchors\": []' in messages[-1]['content']
    selector.observe({'tool': 'command', 'argv': ['python', '-m', 'pytest', '-q']},
                     {'rc': 0, 'stdout': '11 passed', 'stderr': ''})
    selector.build([], 2000, {'latest_test': 0})
    assert events[-1]['phase'] == 'finish'
