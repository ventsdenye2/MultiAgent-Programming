"""Offline regressions using the real upstream agent, executor and OpenAI SDK."""
import json
from pathlib import Path
import sys

import pytest

import course_agent
import httpx
from smolagents import CodeAgent, LocalPythonExecutor

from course_agent.audit import AuditedOpenAIModel, RequestAudit, contains
from course_agent.cli import execute
from course_agent.context import EvidenceContext
from course_agent.engine import CourseCodeAgent, make_agent
from course_agent.policy import load_task
from course_agent.recording import RunLog
from course_agent.session import CourseSession
from verify_vendor import verify

CONFIG = {'model': 'deepseek-flash', 'base_url': 'https://offline.invalid/v1',
          'key_env': 'OFFLINE_TEST_KEY', 'read_only': True, 'max_steps': 8,
          'verify_commands': []}


def response(content, reason='stop', usage=True):
    payload = {'id': 'offline-test', 'object': 'chat.completion', 'created': 0,
               'model': 'deepseek-flash', 'choices': [{'index': 0, 'finish_reason': reason,
               'message': {'role': 'assistant', 'content': content}}]}
    if usage:
        payload['usage'] = {'prompt_tokens': 123, 'completion_tokens': 45, 'total_tokens': 168}
    return payload


def legacy_code(text):
    return '<code>\n' + text + '\n</code>'


def code(text):
    return '```python\n' + text + '\n```'


def run_script(tmp_path, replies, config=None, profile='generic', setup=None, context_mode='evidence'):
    repo, out = tmp_path / 'repo', tmp_path / 'run'
    repo.mkdir()
    if setup:
        setup(repo)
    cfg = CONFIG | (config or {})
    spec = load_task('Complete the requested local task.', repo, cfg, profile)
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        item = replies[len(calls) - 1]
        if callable(item):
            item = item(calls[-1])
        if isinstance(item, httpx.Response):
            return item
        return httpx.Response(200, json=item if isinstance(item, dict) else response(code(item)))
    rc, result = execute(spec, cfg, out, transport=httpx.MockTransport(handler), api_key='offline-test',
                         context_mode=context_mode)
    events = [json.loads(line) for line in (out / 'run.log').read_text().splitlines()]
    return rc, result, calls, events


DONE = "update_plan(items=[{'title':'complete task','status':'done'}])"


def test_vendor_and_no_forked_kernel():
    assert verify()['verified_files'] == 24
    assert CourseCodeAgent._run_stream is CodeAgent._run_stream
    assert CourseCodeAgent._step_stream is CodeAgent._step_stream
    assert CourseCodeAgent.create_python_executor is CodeAgent.create_python_executor


def test_upstream_variable_persistence_and_error_recovery(tmp_path):
    rc, result, calls, events = run_script(tmp_path, [
        DONE + '\nx=41\nprint(undefined_name)',
        "assert x+1 == 42\nfinal_answer('42')",
    ])
    assert rc == 0, result
    assert len(calls) == 2
    assert contains(calls[1], 'undefined_name')
    assert any(e['event'] == 'agent_error' and e['error_type'] == 'AgentExecutionError' for e in events)
    assert result['usage']['prompt_tokens'] == 246
    assert result['usage']['complete']


def test_official_parser_recovers_and_records_error(tmp_path):
    rc, result, calls, events = run_script(tmp_path, [response('no code block'), DONE + "\nfinal_answer('ok')"])
    assert rc == 0, result
    assert contains(calls[1], 'Error in code parsing')
    assert any(e.get('error_type') == 'AgentParsingError' for e in events)


def test_markdown_protocol_ignores_xml_marker_in_prose_and_matches_wire_size(tmp_path):
    # The real failed source response mentioned <code> in its explanation;
    # the XML parser treated that mention as the start of the executable body.
    first = 'The previous <code> marker was only explanatory text.\n' + code(DONE + '\nvalue=41')
    rc, result, calls, events = run_script(tmp_path, [response(first), "final_answer(str(value+1))"])
    assert rc == 0 and result['answer'] == '42', result
    assert not any(e['event'] == 'agent_error' for e in events)
    assert all(call['stop'] == ['Observation:', 'Calling tools:'] for call in calls)
    assert contains(calls[1], first)
    estimates = [e['estimated_body_chars'] for e in events if e['event'] == 'context_selection']
    actual = [e['chars'] for e in events if e['event'] == 'model_request']
    assert estimates == actual


def test_dsml_failure_uses_upstream_recovery_without_a_second_action_parser(tmp_path):
    malformed = '<｜｜DSML｜｜ calls><｜｜DSML｜｜ invoke name="task_status"></｜｜DSML｜｜ invoke></｜｜DSML｜｜ calls>'
    rc, result, calls, events = run_script(tmp_path, [response(malformed), DONE + "\nfinal_answer('Recovered')"])
    assert rc == 0, result
    errors = [e for e in events if e['event'] == 'agent_error']
    assert len(errors) == 1 and errors[0]['error_type'] == 'AgentParsingError'
    assert contains(calls[1], '```python')
    assert not any(e.get('tool') == 'task_status' for e in events if e['event'] == 'tool_call')


def test_unsupported_os_import_recovers_with_declared_file_tools(tmp_path):
    def setup(repo):
        (repo / 'message.txt').write_text('Read using the tool.\n')
    rc, result, calls, events = run_script(tmp_path, [
        'import os',
        DONE + "\nr=read_file(path='message.txt')",
        "final_answer(r['content'])",
    ], setup=setup)
    assert rc == 0 and result['answer'] == 'Read using the tool.\n', result
    assert contains(calls[0], 'os and pathlib are unavailable in action code')
    errors = [e for e in events if e['event'] == 'agent_error']
    assert len(errors) == 1 and 'Import of os is not allowed' in errors[0]['error']
    assert any(e['event'] == 'file_read' and e['path'] == 'message.txt' for e in events)


def test_empty_truncated_response_has_distinct_classification(tmp_path):
    rc, result, calls, events = run_script(tmp_path, [response('', 'length'), DONE + "\nfinal_answer('ok')"])
    assert rc == 0, result
    assert any(e.get('classification') == 'truncated_empty' for e in events)
    # Upstream accepts empty Python as a no-op; keep raw classification separate
    # and make the next request explain it rather than forging a parser error.
    assert contains(calls[1], 'truncated_empty')
    assert len(calls) == 2


def test_budget_has_no_extra_final_answer_request(tmp_path):
    rc, result, calls, events = run_script(tmp_path, ['print(1)'], {'max_steps': 1})
    assert rc == 1
    assert len(calls) == 1
    assert result['reason'] == 'MAX_STEPS_NO_EXTRA_REQUEST'
    assert result['usage']['requests'] == 1


def test_no_sdk_or_framework_network_retry(tmp_path):
    rc, result, calls, events = run_script(tmp_path, [httpx.Response(429, json={'error': {'message': 'rate limit'}})])
    assert rc == 1
    assert len(calls) == 1
    assert not result['usage']['complete']
    assert len([e for e in events if e['event'] == 'model_error']) == 1


def test_actual_body_has_protocol_and_balanced_raw_audit(tmp_path):
    rc, result, calls, events = run_script(tmp_path, [DONE + "\nfinal_answer('ok')"])
    assert rc == 0, result
    assert calls[0]['max_tokens'] == 4096
    assert calls[0]['thinking'] == {'type': 'disabled'}
    assert 'extra_body' not in calls[0]
    assert [e['body'] for e in events if e['event'] == 'model_request'] == calls
    assert len(json.dumps(calls[0], ensure_ascii=False, separators=(',', ':'))) <= 32000
    assert len([e for e in events if e['event'] == 'model_response']) == 1


def test_real_file_tools_pytest_and_final_checks(tmp_path):
    def setup(repo):
        (repo / 'calc.py').write_text('def answer():\n    return 0\n')
        (repo / 'test_calc.py').write_text('from calc import answer\ndef test_answer():\n    assert answer() == 42\n')
    plan = "update_plan(items=[{'title':'fix answer','status':'doing'}])"
    rc, result, calls, events = run_script(tmp_path, [
        plan + "\nrun_command(argv=['python','-m','pytest','-q'])\nr=read_file(path='calc.py')\nprint(r)",
        "write_file(path='calc.py',content='def answer():\\n    return 42\\n',expected_hash=r['file_hash'])\n"
        "run_command(argv=['python','-m','pytest','-q'])\n"
        "update_plan(items=[{'title':'fix answer','status':'done'}])\nfinal_answer('Fixed and tested')",
    ], {'read_only': False, 'editable': ['calc.py'], 'verify_commands': [['python', '-m', 'pytest', '-q']]}, setup=setup)
    assert rc == 0, result
    assert (tmp_path / 'repo/calc.py').read_text() == 'def answer():\n    return 42\n'
    assert '+    return 42' in (tmp_path / 'run/patch.diff').read_text()
    assert [e['rc'] for e in events if e['event'] == 'command_result'] == [1, 0]
    assert any(e['event'] == 'file_write' and 'return 42' in e['content'] for e in events)
    # The baseline course parser must accept the logs, including wrapped tool events.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.contracts import read_events
    assert read_events(tmp_path / 'run/run.log')[1] == []


def test_final_answer_check_is_upstream_recoverable(tmp_path):
    rc, result, calls, events = run_script(tmp_path, ["final_answer('premature')", DONE + "\nfinal_answer('ok')"])
    assert rc == 0, result
    assert contains(calls[1], 'finish all plan items')


def test_context_guard_prevents_wire_request(tmp_path):
    rc, result, calls, events = run_script(tmp_path, [], {'request_chars': 2000, 'context_chars_smol': 1900})
    assert rc == 1
    assert not calls
    assert result['usage']['requests'] == 0


def test_actual_http_guard_in_upstream_context_mode(tmp_path):
    rc, result, calls, events = run_script(tmp_path, [], {'request_chars': 2000, 'context_chars_smol': 1900},
                                         context_mode='upstream')
    assert rc == 1 and not calls
    assert result['reason'] == 'REQUEST_CHAR_BUDGET'
    assert any(e['event'] == 'request_blocked' for e in events)


def test_official_upstream_context_mode_runs(tmp_path):
    rc, result, calls, events = run_script(tmp_path, [DONE + "\nx=7", "final_answer(str(x))"],
                                         context_mode='upstream')
    assert rc == 0, result
    assert result['answer'] == '7'
    assert not any(e['event'] == 'context_selection' for e in events)


def test_workspace_boundaries_and_stale_hash(tmp_path):
    from course_agent.workspace import WorkspaceTools
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'a.py').write_text('before')
    tool = WorkspaceTools(repo, tmp_path / 'out', ['a.py'], lambda *a, **k: None)
    snapshot = tool.invoke('read_file', {'path': 'a.py'})
    (repo / 'a.py').write_text('external change')
    with pytest.raises(ValueError, match='hash changed'):
        tool.invoke('write_file', {'path': 'a.py', 'content': 'overwrite', 'expected_hash': snapshot['file_hash']})
    with pytest.raises(ValueError):
        tool.invoke('read_file', {'path': '../outside'})
    with pytest.raises(ValueError):
        tool.invoke('write_file', {'path': 'test_a.py', 'content': 'bad', 'expected_hash': 'missing'})
    assert (repo / 'a.py').read_text() == 'external change'


def make_session(tmp_path, profile='generic', config=None, text='Read the source and complete the task.'):
    repo = tmp_path / 'repo'
    repo.mkdir()
    cfg = CONFIG | (config or {})
    contract = load_task(text, repo, cfg, profile)
    log = RunLog(tmp_path / 'run')
    session = CourseSession(contract, tmp_path / 'run', log, cfg)
    audit = RequestAudit(contract, log, session.evidence)
    model = AuditedOpenAIModel(cfg, audit, 'offline', transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    context = EvidenceContext(session)
    session.context, session.audit = context, audit
    agent = make_agent(model, session, context)
    return session, context, agent, model, log


def test_dedup_repeated_full_reads_and_version_invalidation(tmp_path):
    session, context, agent, model, log = make_session(tmp_path)
    try:
        path = session.contract.repo / 'data.py'
        original = 'UNIQUE_ORIGINAL_' + 'x' * 2000
        path.write_text(original)
        a = session.invoke('read_file', {'path': 'data.py'})
        b = session.invoke('read_file', {'path': 'data.py'})
        assert a['evidence_ids'] == b['evidence_ids']
        assert len(session.evidence.items) == 1
        from smolagents.memory import TaskStep
        agent.memory.steps.append(TaskStep('Inspect the supplied file.'))
        body = context.build(agent.memory, model)
        assert sum(str(m.content).count('UNIQUE_ORIGINAL_') for m in body) == 1
        path.write_text('CHANGED')
        session.evidence.refresh()
        assert not session.evidence.items[a['evidence_ids'][0]].valid
    finally:
        model.close()
        log.close()


def test_eight_evidence_items_recalled_in_bounded_batches(tmp_path):
    session, context, agent, model, log = make_session(tmp_path)
    try:
        from smolagents.memory import TaskStep
        agent.memory.steps.append(TaskStep('Read eight documents.'))
        ids = []
        for i in range(8):
            path = session.contract.repo / f'doc{i}.txt'
            path.write_text(f'DOC_{i}_' + str(i) * 4000)
            ids += session.invoke('read_file', {'path': path.name})['evidence_ids']
        accepted = session.evidence.recall(ids, 8000)
        assert accepted['scheduled'] and accepted['pending']
        seen = set()
        for number in range(1, 9):
            messages = context.build(agent.memory, model)
            assert model.estimate(messages) <= 32000
            body = {'messages': [m.dict() for m in messages]}
            session.evidence.mark_exposed(body, response(code('print(1)')), number)
            # Ordinary documents may now span requests. Only fully delivered
            # ranges enter exposed; current still means complete text here.
            seen |= session.evidence.exposed
            if not session.evidence.pending:
                break
        assert seen == set(ids)
        assert not session.evidence.pending
    finally:
        model.close()
        log.close()
