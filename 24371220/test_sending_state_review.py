"""Independent regressions for bounded HTTP facts and read lifecycle."""
import json

import httpx
import pytest
import course_agent  # Register the verified vendored upstream package first.
from smolagents.memory import ActionStep, TaskStep
from smolagents.monitoring import Timing

from course_agent.audit import AuditedOpenAIModel, RequestAudit, contains, strings
from course_agent.context import EvidenceContext
from course_agent.engine import make_agent
from course_agent.policy import load_task
from course_agent.recording import RunLog
from course_agent.session import CourseSession
from test_smolagents import CONFIG, code, response


@pytest.fixture
def wire_session(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    path = 'nested/' + 'long_directory_' * 8 + '/a.py'
    target = repo / path
    target.parent.mkdir(parents=True)
    target.write_text('value = 1\n' + '# original context\n' * 1800)
    cfg = CONFIG | {'read_only': False, 'editable': [path], 'verify_commands': []}
    spec = load_task('Read and edit the allowed file.', repo, cfg, 'generic')
    log = RunLog(tmp_path / 'run')
    session = CourseSession(spec, tmp_path / 'run', log, cfg)
    audit = RequestAudit(spec, log, session.evidence)
    bodies = []
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=response(code('print(1)')))
    model = AuditedOpenAIModel(cfg, audit, 'offline', httpx.MockTransport(handler))
    context = EvidenceContext(session)
    session.context, session.audit = context, audit
    agent = make_agent(model, session, context)
    agent.memory.steps.append(TaskStep(session.task_prompt()))
    session.invoke('update_plan', {'items': [{'title': 'Read and edit', 'status': 'doing'}]})
    yield session, context, agent, model, bodies, path
    model.close()
    log.close()


def test_large_originals_keep_complete_write_hash_path_and_failure_on_http(wire_session):
    session, context, agent, model, bodies, path = wire_session
    session.invoke('read_file', {'path': path})
    digest = 'abc12345' * 8
    session.evidence.recent_results = [
        {'tool': 'replace_text', 'result': {'path': path, 'changed': True, 'file_hash': digest}},
        {'tool': 'run_command', 'result': {'rc': 1, 'timed_out': False,
          'stdout': 'FAILED_HEAD\n' + 'long output\n' * 4000 + 'FAILED_TAIL',
          'stderr': 'ERROR_HEAD\n' + 'details\n' * 4000 + 'ERROR_TAIL'}},
    ]
    agent.memory.steps.append(ActionStep(step_number=1, timing=Timing(start_time=0, end_time=1),
                                          model_output=code('print(1)'), code_action='print(1)',
                                          observations='long executor output\n' * 4000))
    model.generate(context.build(agent.memory, model))
    assert len(json.dumps(bodies[-1], ensure_ascii=False, separators=(',', ':'))) <= 32000
    text = '\n'.join(strings(bodies[-1]['messages']))
    marker = 'Recent project tool results:\n'
    facts, _ = json.JSONDecoder().raw_decode(text.split(marker, 1)[1])
    assert facts[0]['result'] == {'path': path, 'changed': True, 'file_hash': digest}
    assert facts[1]['result']['rc'] == 1
    assert facts[1]['result']['timed_out'] is False
    for token in ('FAILED_HEAD', 'FAILED_TAIL', 'ERROR_HEAD', 'ERROR_TAIL'):
        assert contains(bodies[-1], token)


def test_registered_read_is_not_http_delivery_and_write_does_not_reopen_first_read(wire_session):
    session, context, agent, model, bodies, path = wire_session
    original = session.invoke('read_file', {'path': path})
    assert path in session.evidence.full_reads
    assert not session.evidence.file_exposed(path)
    with pytest.raises(ValueError, match='Edit prerequisites'):
        session._before_write({'path': path})
    for _ in range(12):
        model.generate(context.build(agent.memory, model))
        if session.evidence.file_exposed(path):
            break
    assert session.evidence.file_exposed(path)
    session.invoke('replace_text', {'path': path, 'old_text': 'value = 1',
                                  'new_text': 'value = 2', 'expected_hash': original['file_hash']})
    assert not session.evidence.file_exposed(path)
    assert path not in session.evidence.full_reads
    assert not session.progress().evidence_missing
    assert session.progress().phase == 'finish_plan'
    model.generate(context.build(agent.memory, model))
    assert contains(bodies[-1], '"phase":"finish_plan"')
    assert contains(bodies[-1], path)
