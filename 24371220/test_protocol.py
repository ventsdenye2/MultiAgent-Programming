"""Real CodeAgent/SDK/executor regressions; no provider requests."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_smolagents import run_script, response, DONE
from course_agent.protocol import parse_dsml, compile_calls, ProtocolError


def invoke(name, **args):
    params = ''.join('<｜｜DSML｜｜ parameter name="' + k + '" string="' +
                     ('true' if isinstance(v, str) else 'false') + '">' +
                     (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)) +
                     '</｜｜DSML｜｜ parameter>' for k, v in args.items())
    return '<｜｜DSML｜｜ invoke name="' + name + '">' + params + '</｜｜DSML｜｜ invoke>'


def dsml(*calls):
    return '<｜｜DSML｜｜ calls>\n' + '\n'.join(calls) + '\n</｜｜DSML｜｜ calls>'


HISTORICAL = json.loads((Path(__file__).parent / 'test_fixtures/dsml_responses.json').read_text())


@pytest.mark.parametrize('fixture', HISTORICAL, ids=lambda f: f"{f['sample']}-R{f['request']}")
def test_historical_responses_execute_once(tmp_path, fixture):
    def setup(repo):
        (repo / 'deepinfer').mkdir()
        (repo / 'deepinfer/environ.py').write_text('line\n' * 240)
        (repo / 'deepinfer/__init__.py').write_text('# package\n')
    rc, result, calls, events = run_script(tmp_path, [response(fixture['content']), DONE + "\nfinal_answer('ok')"],
                                          {'use_structured_outputs_internally': False}, setup=setup)
    assert rc == 0, result
    expected = parse_dsml(fixture['content'])[0]
    executed = [e for e in events if e['event'] == 'tool_call' and e['tool'] == expected['name']]
    assert len(executed) == 1 and executed[0]['arguments'] == expected['arguments']
    assert len(calls) == 2 and result['usage']['complete']
    assert not any(e['event'] == 'agent_error' for e in events)
    assert next(e for e in events if e['event'] == 'model_response')['response']['choices'][0]['message']['content'] == fixture['content']


@pytest.mark.parametrize('structured', [False, True])
def test_native_variables_and_dsml_final_check(tmp_path, structured):
    rc, result, calls, events = run_script(tmp_path, [
        'value=41', response(dsml(invoke('final_answer', answer='premature'))),
        DONE + '\nassert value == 41', response(dsml(invoke('final_answer', answer='done'))),
    ], {'use_structured_outputs_internally': structured})
    assert rc == 0 and result['answer'] == 'done', result
    assert len(calls) == 4
    errors = [e for e in events if e['event'] == 'agent_error']
    assert len(errors) == 1 and 'finish all plan items' in errors[0]['error']
    assert len([e for e in events if e['event'] == 'protocol_adapter']) == 2


def test_literal_data_is_not_executed_or_normalized():
    value = '  中文\n"\\ &amp; <xml>\'); final_answer("injected") #  '
    schema = {'type': 'object', 'properties': {'value': {'type': 'string'}, 'data': {'type': 'object'}},
              'required': ['value', 'data'], 'additionalProperties': False}
    data = {'array': [True, False, None, 42, 1.5, {'nested': 'yes'}]}
    calls = parse_dsml(dsml(invoke('example', value=value, data=data)))
    code = compile_calls(calls, {'example': SimpleNamespace(parameters=schema)})
    node = ast.parse(code).body[0].value.args[0]
    assert ast.literal_eval(node.keywords[0].value) == value
    assert ast.literal_eval(node.keywords[1].value) == data
    assert len(ast.parse(code).body) == 1


@pytest.mark.parametrize('text', [
    dsml(), dsml(invoke('task_status'))[:-1],
    dsml(invoke('task_status')) + dsml(invoke('task_status')),
    dsml(invoke('task_status')).replace('</｜｜DSML｜｜ invoke>', ''),
    dsml(invoke('x', a=1)).replace('>1</', '>NaN</'),
    dsml(invoke('x', a=1)).replace('>1</', '>1e999</'),
    dsml(invoke('x', a=1)).replace('>1</', '>__import__("os")</'),
    dsml(invoke('x', a=1)).replace('>1</', '>{"a":1,"a":2}</'),
    dsml(invoke('x', a='x')).replace('</｜｜DSML｜｜ parameter>', '</｜｜DSML｜｜ parameter><｜｜DSML｜｜ parameter name="a" string="true">y</｜｜DSML｜｜ parameter>'),
    dsml(*[invoke('task_status')] * 33),
])
def test_bad_syntax_rejected(text):
    with pytest.raises(ProtocolError):
        parse_dsml(text)


@pytest.mark.parametrize('bad', [
    invoke('not_registered'), invoke('read_file'), invoke('task_status', extra=1),
    invoke('read_range', path='a', start_line=True, end_line=2),
])
def test_batch_prevalidation_has_no_partial_execution(tmp_path, bad):
    text = dsml(invoke('task_status'), bad)
    rc, result, _, events = run_script(tmp_path, [response(text), DONE + "\nfinal_answer('ok')"])
    assert rc == 0, result
    assert not any(e['event'] == 'tool_call' and e['tool'] == 'task_status' for e in events)
    assert any(e['event'] == 'protocol_adapter' and e['status'] == 'rejected' for e in events)
    assert any(e.get('error_type') == 'AgentParsingError' for e in events)


def test_runtime_failure_keeps_prior_actions_without_replay(tmp_path):
    text = dsml(invoke('update_plan', items=[{'title': 'work', 'status': 'doing'}]),
                invoke('read_file', path='missing.txt'), invoke('task_status'))
    rc, result, _, events = run_script(tmp_path, [response(text),
        "update_plan(items=[{'title':'work','status':'done'}])\nfinal_answer('ok')"])
    assert rc == 0, result
    names = [e['tool'] for e in events if e['event'] == 'tool_call']
    assert names == ['update_plan', 'read_file', 'update_plan']


@pytest.mark.parametrize('kind', ['truncated', 'mixed', 'mixed_inline', 'final_first'])
def test_reject_ambiguous_actions(tmp_path, kind):
    text = dsml(invoke('task_status'))
    if kind == 'mixed':
        text = '```python\nprint(task_status())\n```\n' + text
    if kind == 'mixed_inline':
        text = '```python\nprint(task_status())\n``` also ' + text
    if kind == 'final_first':
        text = dsml(invoke('final_answer', answer='bad'), invoke('task_status'))
    rc, result, _, events = run_script(tmp_path, [response(text, 'length' if kind == 'truncated' else 'stop'),
        DONE + "\nfinal_answer('ok')"], {'use_structured_outputs_internally': False})
    assert rc == 0, result
    assert not any(e['event'] == 'tool_call' and e['tool'] == 'task_status' for e in events)
    assert next(e for e in events if e['event'] == 'protocol_adapter')['status'] == 'rejected'


def test_note_uses_raw_response_provenance(tmp_path):
    note = 'Exact model-written note with "quotes", 中文 and a newline.\nDo not rewrite it.'
    def setup(repo):
        (repo / 'source.txt').write_text('Original evidence for the note.\n')
    def reply(body):
        import re
        ids = re.findall(r'ev-[a-f0-9]{20}', json.dumps(body))
        return response(dsml(invoke('write_note', title='note', content=note, evidence_ids=[ids[0]])))
    rc, result, _, events = run_script(tmp_path, ["read_file(path='source.txt')", reply,
        DONE + "\nfinal_answer('ok')"], setup=setup)
    assert rc == 0, result
    assert next(e for e in events if e['event'] == 'context_note')['content'] == note
    raw = next(e for e in events if e['event'] == 'model_response' and e['number'] == 2)
    assert note in raw['response']['choices'][0]['message']['content']


@pytest.mark.parametrize('structured', [True, False])
def test_dsml_write_preserves_hash_and_read_gates(tmp_path, structured):
    content = 'after\n```python\nprint("quoted")\n```\n</code> &amp; 中文'
    def setup(repo):
        (repo / 'a.txt').write_text('before')
    def write(body):
        import hashlib
        return response(dsml(invoke('write_file', path='a.txt', content=content,
                                    expected_hash=hashlib.sha256(b'before').hexdigest())))
    rc, result, _, events = run_script(tmp_path, [
        "update_plan(items=[{'title':'work','status':'doing'}])\nread_file(path='a.txt')", write,
        "update_plan(items=[{'title':'work','status':'done'}])\nfinal_answer('ok')",
    ], {'read_only': False, 'editable': ['a.txt'], 'use_structured_outputs_internally': structured}, setup=setup)
    assert rc == 0, result
    assert (tmp_path / 'repo/a.txt').read_text() == content
    assert len([e for e in events if e['event'] == 'file_write']) == 1


def test_native_code_containing_dsml_data_is_unchanged(tmp_path):
    text = dsml(invoke('task_status'))
    rc, result, _, events = run_script(tmp_path, [DONE + '\ndata=' + repr(text) + "\nfinal_answer(data)"],
                                      {'use_structured_outputs_internally': False})
    assert rc == 0 and result['answer'] == text
    assert not any(e['event'] == 'protocol_adapter' for e in events)


@pytest.mark.parametrize('failure', ['unread', 'stale', 'outside'])
def test_dsml_cannot_bypass_write_guards(tmp_path, failure):
    import hashlib
    def setup(repo):
        (repo / 'a.txt').write_text('before')
    first = "update_plan(items=[{'title':'work','status':'doing'}])"
    if failure != 'unread':
        first += "\nread_file(path='a.txt')"
    text = dsml(invoke('write_file', path='../outside.txt' if failure == 'outside' else 'a.txt',
                       content='after', expected_hash='stale' if failure == 'stale' else hashlib.sha256(b'before').hexdigest()))
    rc, result, _, events = run_script(tmp_path, [first, response(text)],
        {'read_only': False, 'editable': ['a.txt'], 'max_steps': 2}, setup=setup)
    assert rc == 1 and (tmp_path / 'repo/a.txt').read_text() == 'before'
    assert not (tmp_path / 'outside.txt').exists()
    assert any(e.get('error_type') == 'AgentExecutionError' for e in events)
    assert not any(e['event'] == 'file_write' for e in events)


def test_saved_answer_and_section_use_real_paper_tools(tmp_path):
    from test_static_context import make_paper_session
    from smolagents.models import ChatMessage, MessageRole
    session, _, agent, model, log = make_paper_session(tmp_path, False, 'Read paper.')
    try:
        (tmp_path / 'repo/paper.pdf').write_text('synthetic PDF version')
        quote = 'This synthetic quotation supports the offline provenance check.'
        eid = session.evidence._add('paper.pdf', session.workspace.current_hash('paper.pdf'),
                                    'page:1', quote, page=1)
        session.evidence.exposed.add(eid)
        text = dsml(invoke('save_answer', section='overview', question_id='categories',
                            answer={'value': ['synthetic']}, evidence_id=eid, page=1, quote=quote),
                    invoke('save_section', section='overview', summary='Summary', application='Application'))
        adapted = model.protocol_adapter.adapt(ChatMessage(role=MessageRole.ASSISTANT, content=text))
        agent.python_executor.send_tools(agent.tools)
        agent.python_executor(json.loads(adapted.content)['code'])
        assert session.evidence.answers['overview']['categories']['quote'] == quote
        assert session.evidence.section_text['overview']['summary'] == 'Summary'
        bad = dsml(invoke('save_answer', section='overview', question_id='categories',
                          answer={'value': ['wrong']}, evidence_id=eid, page=1,
                          quote='This quote does not exist in the actual evidence.'))
        adapted = model.protocol_adapter.adapt(ChatMessage(role=MessageRole.ASSISTANT, content=bad))
        with pytest.raises(Exception, match='quote'):
            agent.python_executor(json.loads(adapted.content)['code'])
        assert session.evidence.answers['overview']['categories']['answer'] == ['synthetic']
    finally:
        model.close()
        log.close()
