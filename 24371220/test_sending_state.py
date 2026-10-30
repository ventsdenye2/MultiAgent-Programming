"""Offline checks for the wire view and same-action completion."""
import json
import tarfile

import httpx

from course_agent.audit import AuditedOpenAIModel, contains, request_size, strings
from test_smolagents import CONFIG, code, response, run_script
from test_smolagents_materials import MATERIALS, build_session


def test_wire_view_and_last_response_complete_with_real_test(tmp_path):
    def setup(repo):
        (repo / 'a.py').write_text('value = 1\n')
    replies = [
        "update_plan(items=[{'title':'edit','status':'doing'}])\nr=read_file(path='a.py')",
        "replace_text(path='a.py', old_text='value = 1', new_text='value = 2', expected_hash=r['file_hash'])",
        "result=run_command(argv=['python','-m','pytest','-q'])\n"
        "if result['rc'] == 0:\n"
        "    items=task_status()['plan']\n"
        "    items[0]['status']='done'\n"
        "    update_plan(items=items)\n"
        "    final_answer('verified')",
    ]
    def setup_tests(repo):
        setup(repo)
        (repo / 'test_a.py').write_text('from a import value\ndef test_value():\n    assert value == 2\n')
    # Baseline must be run before the write.
    replies[0] += "\nrun_command(argv=['python','-m','pytest','-q'])"
    rc, result, bodies, events = run_script(tmp_path, replies, {
        'read_only': False, 'editable': ['a.py'], 'max_steps': 3,
        'verify_commands': [['python','-m','pytest','-q']]}, setup=setup_tests)
    assert rc == 0, result
    assert contains(bodies[1], 'value = 1')
    assert contains(bodies[2], '"requests_after_response":0')
    assert any(e.get('event') == 'command_result' and e.get('rc') == 0 for e in events)
    assert len(bodies) == 3


def test_source_wire_state_tracks_actual_exposure_and_write(tmp_path, build_session):
    source = MATERIALS / '公开任务/题目2'
    repo = tmp_path / 'source_repo'
    repo.mkdir()
    targets = ['deepinfer/environ.py', 'deepinfer/logger.py', 'deepinfer/engine/stats_logger.py']
    with tarfile.open(source / 'DeepInfer-774ce244.tar.gz') as archive:
        for rel in targets:
            member = next(m for m in archive.getmembers() if m.name.endswith('/' + rel))
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.extractfile(member).read())
    session, context, agent, old_model = build_session('source', repo, (source / 'task.md').read_text())
    reads = {rel: session.invoke('read_file', {'path': rel}) for rel in targets}
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=response(code('print(1)')))
    model = AuditedOpenAIModel(CONFIG | {'max_steps': 40, 'max_tokens': 16384,
                                        'thinking': 'enabled', 'reasoning_effort': 'high'}, session.audit, 'offline',
                              transport=httpx.MockTransport(handler))
    def send():
        messages = context.build(agent.memory, model)
        expected = model.measure(messages)
        model.generate(messages, stop_sequences=model.action_stop_sequences,
                       response_format=model.action_response_format)
        assert request_size(bodies[-1]) == expected
        assert expected['chars'] <= 32000
        marker = 'Course progress before this request (evidence offered below may satisfy pending items after delivery):\n'
        text = next(s for s in strings(bodies[-1]['messages']) if marker in s)
        return json.JSONDecoder().raw_decode(text.split(marker, 1)[1])[0]
    try:
        first = send()
        assert first['request_number'] == 1 and first['requests_after_response'] == first['max_requests'] - 1
        assert set(first['full_reads_registered']) == set(targets)
        assert all(v['exposed'] == 0 and v['registered'] > 0 for v in first['required_mechanisms_exposed'].values())
        assert session.status()['requests_left'] == first['requests_after_response']
        second = send()
        assert second['request_number'] == 2
        assert all(v['exposed'] == v['registered'] > 0 for v in second['required_mechanisms_exposed'].values())
        session.invoke('write_file', {'path': targets[0], 'content': reads[targets[0]]['content'] + '\n# offline test\n',
                                      'expected_hash': reads[targets[0]]['file_hash']})
        third = send()
        assert targets[0] not in third['full_reads_registered']
        assert third['first_write_reading_required'] is False
        assert third['requests_after_response'] == session.status()['requests_left']
        assert third['request_number'] == session.audit.calls
    finally:
        model.close()
