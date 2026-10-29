"""Regressions for actual basic-task budgets and evidence delivery, offline only."""
import json
from pathlib import Path
import shutil

import httpx
import pytest

from course_agent.audit import contains, request_size
from course_agent.cli import execute
from smolagents.memory import ActionStep, TaskStep
from smolagents.models import MessageRole
from smolagents.monitoring import Timing
from smolagents.utils import AgentExecutionError
from course_agent.policy import load_task
from test_smolagents import make_session, response, code, legacy_code, run_script, DONE


ROOT = Path(__file__).resolve().parent
FAILED_SMOKE = ROOT / 'experiments/smolagents/smolagents-20261028-225055-084673'


def test_recorded_smoke_reaches_edit_and_passes_public_checks(tmp_path):
    shutil.copytree(FAILED_SMOKE / 'smoke-attempt/before', tmp_path / 'work')
    repo, out = tmp_path / 'work/repo', tmp_path / 'run'
    original = (repo / 'calc.py').read_text(encoding='utf-8')
    events = [json.loads(line) for line in
              (FAILED_SMOKE / 'smoke-attempt/run/run.log').read_text(encoding='utf-8').splitlines()]
    replies = [e['response']['choices'][0]['message']['content'] for e in events if e['event'] == 'model_response']
    # A separate simulated continuation validates execution; these are not new
    # real-model decisions or a paid course pass.
    replies.append(legacy_code("replace_text(path='calc.py', old_text='return price * discount / 100', "
                        "new_text='return price * discount', expected_hash=res['file_hash'])\n"
                        "run_command(argv=['python','-m','pytest','-q'])\n"
                        "for item in plan: item['status']='done'\n"
                        "update_plan(items=plan)\nfinal_answer('Fixed and verified')"))
    cfg = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
    cfg.update(base_url='https://offline.invalid/v1', key_env='OFFLINE_TEST_KEY', max_steps=8,
               code_block_tags=None)  # Preserve the saved run's official XML protocol.
    contract = load_task((tmp_path / 'work/task.md').read_text(encoding='utf-8'), repo, cfg)
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 4:
            assert contains(body, original), 'The first request after read_file must contain the small full source'
        assert request_size(body)['course_content_chars'] <= 15000
        return httpx.Response(200, json=response(replies[len(calls) - 1]))
    rc, result = execute(contract, cfg, out, transport=httpx.MockTransport(handler), api_key='offline-test')
    assert rc == 0, result
    assert len(calls) == 6
    assert 'return price * discount / 100' not in (repo / 'calc.py').read_text(encoding='utf-8')
    import sys
    sys.path.insert(0, str(ROOT.parent))
    from tools.contracts import inspect_process, read_events
    trace, errors = read_events(out / 'run.log')
    assert not errors
    process = inspect_process(trace, {'baseline_test': True, 'post_tests': True, 'context_chars': 16000})
    assert process['passed'], process
    assert any(e.get('event') == 'command_result' and e.get('rc') == 0 and '11 passed' in e.get('stdout', '')
               for e in trace)


def test_reading_without_delivery_cannot_authorize_a_write(tmp_path):
    session, context, agent, model, log = make_session(tmp_path, config={
        'read_only': False, 'editable': ['a.py'], 'verify_commands': []})
    try:
        (session.contract.repo / 'a.py').write_text('value = 1\n')
        session.invoke('update_plan', {'items': [{'title': 'edit', 'status': 'doing'}]})
        read = session.invoke('read_file', {'path': 'a.py'})
        write = {'path': 'a.py', 'content': 'value = 2\n', 'expected_hash': read['file_hash']}
        with pytest.raises(ValueError, match='waiting to be sent'):
            session.invoke('write_file', write)
        agent.memory.steps.append(TaskStep(session.task_prompt()))
        messages = context.build(agent.memory, model)
        session.evidence.mark_exposed({'messages': [m.dict() for m in messages]}, response(code('print(1)')), 1)
        session.invoke('write_file', write)
        # The model-authored version remains editable without rereading it.
        session.invoke('write_file', {**write, 'content': 'value = 3\n',
                                     'expected_hash': session.workspace.current_hash('a.py')})
        (session.contract.repo / 'a.py').write_text('external = 4\n')
        with pytest.raises(ValueError, match='Read the current target'):
            session.invoke('write_file', {**write, 'expected_hash': session.workspace.current_hash('a.py')})
    finally:
        model.close()
        log.close()


def test_partial_file_delivery_requires_complete_actual_ranges(tmp_path):
    session, context, agent, model, log = make_session(tmp_path, profile='basic', config={
        'editable': ['large.py'], 'context_chars': 15000})
    try:
        source = ''.join(f'line_{n} = {n}  # unique source line number {n}\n' for n in range(130))
        path = session.contract.repo / 'large.py'
        path.write_text(source)
        result = session.invoke('read_file', {'path': 'large.py'})
        agent.memory.steps.append(TaskStep(session.task_prompt()))
        positions = {eid: set() for eid in result['evidence_ids']}
        first = context.build(agent.memory, model)
        assert context.last_manifest['delivered_parts']
        assert not session.evidence.file_exposed('large.py')
        session.evidence.mark_exposed({'messages': []}, response(code('print(1)')), 1)
        assert not session.evidence.received_ranges, 'Offered but absent text is not delivered'
        for number in range(2, 15):
            messages = context.build(agent.memory, model)
            assert model.measure(messages)['course_content_chars'] <= 15000
            body = {'messages': [m.dict() for m in messages]}
            for eid, start, end in context.last_manifest['delivered_parts']:
                assert contains(body, session.evidence.render(eid, start, end))
                positions[eid].update(range(start, end))
            session.evidence.mark_exposed(body, response(code('print(1)')), number)
            expected = all(len(positions[eid]) == len(session.evidence.items[eid].text) for eid in positions)
            assert session.evidence.file_exposed('large.py') == expected
            if expected:
                break
            if number == 2:
                before = {eid: list(ranges) for eid, ranges in session.evidence.received_ranges.items()}
                session.invoke('read_file', {'path': 'large.py'})
                assert session.evidence.received_ranges == before
        assert session.evidence.file_exposed('large.py')
        path.write_text('changed version\n')
        session.evidence.refresh()
        assert not session.evidence.file_exposed('large.py')
        assert not session.evidence.received_ranges
    finally:
        model.close()
        log.close()


def test_repeated_large_feedback_never_grows_fixed_status(tmp_path):
    session, context, agent, model, log = make_session(tmp_path, profile='basic', config={
        'editable': ['a.py'], 'context_chars': 15000})
    try:
        agent.memory.steps.append(TaskStep(session.task_prompt()))
        session.evidence.recent_results = [{'tool': 'run_command', 'result': {'stdout': 'huge log\n' * 10000}}] * 4
        error = 'CURRENT_FAILURE: the requested file hash changed; reread the current source.'
        agent.memory.steps.append(ActionStep(step_number=1, timing=Timing(start_time=0, end_time=1),
                                            code_action='read_file(path="a.py")', observations='huge log\n' * 10000,
                                            error=AgentExecutionError(error, agent.logger)))
        for _ in range(8):
            messages = context.build(agent.memory, model)
            assert model.measure(messages)['course_content_chars'] <= 15000
            assert contains({'messages': [m.dict() for m in messages]}, error)
        assert session.progress_monitor.stalled_steps == 0, 'Building context is not an executed model step'
    finally:
        model.close()
        log.close()


def test_long_command_summary_is_observable_without_model_print(tmp_path):
    session, context, agent, model, log = make_session(tmp_path)
    try:
        (session.contract.repo / 'run_checks.py').write_text("print('diagnostic ' * 1300)\n")
        result = session.invoke('run_command', {'argv': ['python', 'run_checks.py']})
        assert len(result['stdout']) >= 12000
        trace = [json.loads(line) for line in (tmp_path / 'run/run.log').read_text().splitlines()]
        recorded = next(e for e in trace if e['event'] == 'command_result')
        assert recorded['stdout'] == result['stdout']
        event = next(e for e in trace if e['event'] == 'context_clip')
        assert event['original_chars'] == len(recorded['stdout'])
        assert event['sent_chars'] == 2400 and event['retained']
    finally:
        model.close()
        log.close()


def test_recorded_plan_error_does_not_starve_source_or_restart_plan(tmp_path):
    archived = ROOT / 'experiments/smolagents/smolagents-20261029-084305-472591'
    shutil.copytree(archived / 'smoke-attempt/before', tmp_path / 'work')
    repo, out = tmp_path / 'work/repo', tmp_path / 'run'
    original = (repo / 'calc.py').read_text(encoding='utf-8')
    events = [json.loads(line) for line in
              (archived / 'smoke-attempt/run/run.log').read_text(encoding='utf-8').splitlines()]
    replies = [e['response']['choices'][0]['message']['content'] for e in events
               if e['event'] == 'model_response'][:6]
    # The first six saved real replies include a plan-schema error and its
    # successful correction. The continuation is explicitly offline/simulated.
    replies.append(legacy_code("import json\n"
                        "print(json.dumps({'stage':'editing'}))\n"
                        "replace_text(path='calc.py', old_text='return price * discount / 100', "
                        "new_text='return price * discount', expected_hash=calc['file_hash'])\n"
                        "run_command(argv=['python','-m','pytest','-q'])\n"
                        "for item in plan['items']: item['status']='done'\n"
                        "update_plan(items=plan['items'])\nfinal_answer('Verified')"))
    cfg = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
    cfg.update(base_url='https://offline.invalid/v1', key_env='OFFLINE_TEST_KEY', max_steps=9,
               code_block_tags=None)
    contract = load_task((tmp_path / 'work/task.md').read_text(encoding='utf-8'), repo, cfg)
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 5:
            assert not contains(body, 'Each plan item requires'), 'A corrected schema error is not current'
        if len(calls) == 7:
            assert contains(body, original), 'A past plan error must not starve the required small source'
        assert request_size(body)['course_content_chars'] <= 15000
        return httpx.Response(200, json=response(replies[len(calls) - 1]))
    rc, result = execute(contract, cfg, out, transport=httpx.MockTransport(handler), api_key='offline-test')
    assert rc == 0, result
    assert len(calls) == 7
    assert 'return price * discount / 100' not in (repo / 'calc.py').read_text(encoding='utf-8')


def test_plan_churn_stops_before_spending_full_call_budget(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'a.py').write_text('value = 1\n')
    cfg = {'base_url':'https://offline.invalid/v1', 'key_env':'OFFLINE_TEST_KEY',
           'model':'test-model', 'max_steps':20, 'editable':['a.py'], 'verify_commands':[]}
    contract = load_task('Update a.py', repo, cfg)
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        status = 'doing' if len(calls) % 2 else 'todo'
        reply = code("update_plan(items=[{'title':'Read and edit','status':'" + status + "'}])")
        return httpx.Response(200, json=response(reply))
    rc, result = execute(contract, cfg, tmp_path / 'run', transport=httpx.MockTransport(handler), api_key='offline-test')
    assert rc != 0 and 'NO_PROGRESS' in result['reason']
    assert len(calls) == 6
    assert result['usage']['requests'] == 6


def test_ready_to_edit_status_precedes_post_change_verification(tmp_path):
    session, context, agent, model, log = make_session(tmp_path, profile='basic', config={
        'read_only': False, 'editable': ['a.py'], 'context_chars': 15000})
    try:
        (session.contract.repo / 'a.py').write_text('value = 1\n')
        session.invoke('update_plan', {'items': [{'title':'Edit and verify', 'status':'doing'}]})
        session.invoke('read_file', {'path':'a.py'})
        agent.memory.steps.append(TaskStep(session.task_prompt()))
        messages = context.build(agent.memory, model)
        session.evidence.mark_exposed({'messages':[m.dict() for m in messages]}, response(code('print(1)')), 1)
        session.baselines.add(('python','-m','pytest','-q'))
        remaining = session.status()['remaining']
        assert remaining[0] == 'make the requested change'
        assert remaining[1] == 'verify current files: python -m pytest -q'
    finally:
        model.close()
        log.close()


def test_concurrent_evaluation_is_rejected_before_preflight():
    import fcntl
    import subprocess
    import sys
    lockfile = ROOT / 'experiments/smolagents/.evaluation.lock'
    with lockfile.open('a+') as locked:
        fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run([sys.executable, 'evaluate_course.py', '--preflight-only'],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert 'Another evaluation is active' in result.stderr
    assert 'Native run:' not in result.stdout


def test_recorded_missing_plan_is_retained_and_can_recover(tmp_path):
    archived = ROOT / 'experiments/smolagents/smolagents-20261029-085636-296737'
    shutil.copytree(archived / 'smoke-attempt/before', tmp_path / 'work')
    repo, out = tmp_path / 'work/repo', tmp_path / 'run'
    original = (repo / 'calc.py').read_text(encoding='utf-8')
    events = [json.loads(line) for line in
              (archived / 'smoke-attempt/run/run.log').read_text(encoding='utf-8').splitlines()]
    plan = next(e['items'] for e in events if e['event'] == 'plan')
    replies = [e['response']['choices'][0]['message']['content'] for e in events
               if e['event'] == 'model_response'][:3]
    replies += [legacy_code("items = task_status()['plan']\nitems[0]['status']='done'\n"
                     "update_plan(items=items)\ncalc = read_file(path='calc.py')"),
                legacy_code("replace_text(path='calc.py', old_text='return price * discount / 100', "
                     "new_text='return price * discount', expected_hash=calc['file_hash'])\n"
                     "run_command(argv=['python','-m','pytest','-q'])\n"
                     "for item in items: item['status']='done'\n"
                     "update_plan(items=items)\nfinal_answer('Verified')")]
    cfg = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
    cfg.update(base_url='https://offline.invalid/v1', key_env='OFFLINE_TEST_KEY', max_steps=8,
               code_block_tags=None)
    contract = load_task((tmp_path / 'work/task.md').read_text(encoding='utf-8'), repo, cfg)
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) > 1:
            assert contains(body, 'Current plan; retain these exact titles and order')
            for item in plan:
                assert contains(body, item['title'])
        if len(calls) == 4:
            assert contains(body, "task_status()['plan']")
        if len(calls) == 5:
            assert contains(body, original)
        assert request_size(body)['course_content_chars'] <= 15000
        return httpx.Response(200, json=response(replies[len(calls) - 1]))
    rc, result = execute(contract, cfg, out, transport=httpx.MockTransport(handler), api_key='offline-test')
    assert rc == 0, result
    assert len(calls) == 5


def test_project_tools_bind_positional_and_keyword_arguments(tmp_path):
    session, context, agent, model, log = make_session(tmp_path)
    try:
        (session.contract.repo / 'a.py').write_text('value = 1\n')
        tools = {tool.name:tool for tool in session.tools()}
        assert tools['read_file']('a.py')['content'] == 'value = 1\n'
        plan = [{'title':'Read and verify', 'status':'doing'}]
        assert tools['update_plan'](plan)['items'] == plan
        with pytest.raises(TypeError, match='multiple values'):
            tools['read_file']('a.py', path='a.py')
        with pytest.raises(TypeError, match='positional arguments'):
            tools['update_plan'](plan, 'unexpected')
    finally:
        model.close()
        log.close()


def test_verified_changes_remain_visible_until_final_answer(tmp_path):
    def setup(repo):
        (repo / 'calc.py').write_text('def answer():\n    return 0\n')
        (repo / 'test_calc.py').write_text('from calc import answer\ndef test_answer():\n    assert answer() == 42\n')
    def finish(body):
        assert contains(body, '"baseline_done": 1')
        assert contains(body, '"changed_files": ["calc.py"]')
        assert contains(body, '"verified_current": 1')
        assert contains(body, 'Changes and current-file tests are complete')
        return "update_plan([{'title':'Fix and verify','status':'done'}])\nfinal_answer('Verified')"
    rc, result, calls, events = run_script(tmp_path, [
        "update_plan([{'title':'Fix and verify','status':'doing'}])\n"
        "run_command(['python','-m','pytest','-q'], '.')\nr=read_file('calc.py')",
        "write_file('calc.py', 'def answer():\\n    return 42\\n', r['file_hash'])",
        "run_command(['python','-m','pytest','-q'], '.')",
        finish,
    ], {'read_only':False, 'editable':['calc.py'], 'context_chars':15000}, profile='basic', setup=setup)
    assert rc == 0, result
    assert len(calls) == 4
    assert [e['rc'] for e in events if e['event'] == 'command_result'] == [1, 0]


def test_shared_request_cap_applies_across_task_runs(tmp_path, monkeypatch):
    budget = tmp_path / 'budget.json'
    budget.write_text(json.dumps({'limit':2, 'used':0}))
    monkeypatch.setenv('CODE_AGENT_REQUEST_BUDGET_FILE', str(budget))
    for index in range(3):
        root = tmp_path / str(index)
        root.mkdir()
        rc, result, calls, events = run_script(root, [DONE + "\nfinal_answer('ok')"])
        if index < 2:
            assert rc == 0 and len(calls) == 1, result
        else:
            assert rc != 0 and not calls
            assert result['reason'] == 'RUN_REQUEST_BUDGET'
            assert result['usage']['requests'] == 0
    assert json.loads(budget.read_text()) == {'limit':2, 'used':2}


def test_assistant_history_contains_only_complete_code_actions(tmp_path):
    session, context, agent, model, log = make_session(tmp_path)
    try:
        action = 'values = list(range(50))\nprint(values)'
        original = 'I will inspect these values.\n' + code(action)
        agent.memory.steps.append(ActionStep(step_number=1, timing=Timing(start_time=0,end_time=1),
                                            code_action=action, model_output=original, observations='result'))
        short = context._recent(agent.memory, (20, 80, 80))
        assert all(m.role != MessageRole.ASSISTANT for m in short)
        full = context._recent(agent.memory, (1000, 80, 80))
        assert full[0].role == MessageRole.ASSISTANT
        assert full[0].content[0]['text'] == original
        parsed = context._recent(agent.memory, (len(code(action)), 80, 80))
        assert parsed[0].role == MessageRole.ASSISTANT
        assert parsed[0].content[0]['text'] == code(action)
    finally:
        model.close()
        log.close()


def test_distinct_executor_work_is_not_a_repeated_action_cycle(tmp_path):
    replies = [f'value_{n} = {n}' for n in range(8)]
    replies.append(DONE + "\nfinal_answer('Variables prepared')")
    rc, result, calls, events = run_script(tmp_path, replies, {'max_steps':10})
    assert rc == 0, result
    assert len(calls) == 9
    assert not any(e['event'] == 'run_stalled' for e in events)


def test_progress_snapshot_and_final_gate_share_verified_versions(tmp_path):
    session, context, agent, model, log = make_session(tmp_path, profile='basic', config={
        'read_only':False, 'editable':['a.py'], 'context_chars':15000})
    try:
        (session.contract.repo / 'a.py').write_text('value = 1\n')
        session.invoke('update_plan', {'items':[{'title':'Edit and verify','status':'doing'}]})
        session.invoke('read_file', {'path':'a.py'})
        agent.memory.steps.append(TaskStep(session.task_prompt()))
        messages = context.build(agent.memory, model)
        session.evidence.mark_exposed({'messages':[m.dict() for m in messages]}, response(code('print(1)')), 1)
        session.baselines.add(('python','-m','pytest','-q'))
        before = session.progress()
        assert before.phase == 'edit'
        assert before.remaining == session.status()['remaining']
        with pytest.raises(ValueError, match='make the requested change'):
            session.check_final('premature', agent.memory)
        session.invoke('write_file', {'path':'a.py','content':'value = 2\n',
                                     'expected_hash':session.workspace.current_hash('a.py')})
        assert before.phase == 'edit', 'A previously captured snapshot is immutable'
        assert session.progress().phase == 'verify'
        session.verified[('python','-m','pytest','-q')] = session.versions()
        assert session.progress().phase == 'finish_plan'
        session.invoke('update_plan', {'items':[{'title':'Edit and verify','status':'done'}]})
        assert session.progress().ready_for_final
        assert session.check_final('verified', agent.memory)
        session.two_stage = True
        assert not session.progress().ready_for_final
        with pytest.raises(ValueError, match='intermediate first-subtask'):
            session.check_final('missing subtask proof', agent.memory)
        session.stage_one_verified = True
        assert session.progress().ready_for_final
        (session.contract.repo / 'a.py').write_text('value = 3\n')
        assert session.progress().phase == 'verify'
        with pytest.raises(ValueError, match='verify current files'):
            session.check_final('stale verification', agent.memory)
    finally:
        model.close()
        log.close()
