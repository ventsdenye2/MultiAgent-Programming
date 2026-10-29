"""Offline HTTP/kernel regressions for delivery recovery and report lifecycle."""
import json

import httpx
import pytest

from course_agent.audit import AuditedOpenAIModel, BudgetExceeded, RequestAudit, contains
from course_agent.context import EvidenceContext
from course_agent.engine import make_agent
from course_agent.policy import load_task
from course_agent.recording import RunLog
from course_agent.session import CourseSession
from test_smolagents import CONFIG, code, response


@pytest.fixture
def paper_runtime(tmp_path):
    resources = []

    def build(page_texts, replies, *, verify=False):
        repo = tmp_path / 'repo'
        repo.mkdir()
        (repo / 'paper.json').write_text(json.dumps({'required_pages': [1, len(page_texts)]}))
        (repo / 'paper.pdf').write_bytes(b'Offline evidence fixture; PDF parsing is tested on course materials.')
        (repo / 'report.json').write_text('{}')
        if verify:
            (repo / 'test_report.py').write_text(
                "import json\nfrom pathlib import Path\n"
                "def test_report():\n    assert json.loads(Path('report.json').read_text()).get('complete') is True\n")
        cfg = CONFIG | {'read_only': not verify, 'max_steps': len(replies)}
        spec = load_task('Read the PDF and update report.json.', repo, cfg, 'paper')
        if not verify:
            spec.verify_commands = []
        log = RunLog(tmp_path / 'run')
        session = CourseSession(spec, tmp_path / 'run', log, cfg)
        audit = RequestAudit(spec, log, session.evidence)
        calls, snapshots = [], []

        def handler(request):
            calls.append(json.loads(request.content))
            snapshots.append({'pending': set(session.evidence.pending),
                              'exposed': set(session.evidence.exposed)})
            item = replies[len(calls) - 1]
            return httpx.Response(200, json=item(session) if callable(item) else item)

        model = AuditedOpenAIModel(cfg, audit, 'offline', transport=httpx.MockTransport(handler))
        context = EvidenceContext(session)
        session.audit, session.context = audit, context
        agent = make_agent(model, session, context)
        session.invoke('read_file', {'path': 'report.json'})
        # Avoid substituting fake PDF parsing: these are explicit synthetic
        # delivery fixtures; the material suite separately executes read_pdf.py.
        extracted = {'pages': [{'page': n, 'text': text} for n, text in enumerate(page_texts, 1)]}
        session.evidence.observe('read_pdf', {}, extracted)
        page_ids = extracted['evidence_ids']
        resources.append((model, log))
        return session, agent, calls, snapshots, page_ids

    yield build
    for model, log in resources:
        model.close()
        log.close()


@pytest.mark.parametrize('failed_reply', [
    response(''),
    response('', reason='length'),
    response('This response has no executable code block.'),
    response(code("raise ValueError('Recover the delivered batch')")),
], ids=['empty', 'truncated-empty', 'parser-error', 'action-error'])
def test_failed_http_batch_recovers_then_success_advances(paper_runtime, failed_reply):
    pages = [f'PDF_PAGE_{n}_' + str(n) * 14500 for n in range(1, 4)]
    session, agent, calls, snapshots, ids = paper_runtime(pages, [
        failed_reply, response(code("print('Recovered the supplied page.')")),
        response(code("print('Read the next page.')")),
    ])
    with pytest.raises(BudgetExceeded, match='MAX_STEPS_NO_EXTRA_REQUEST'):
        agent.run(session.task_prompt())
    assert len(calls) == 3
    assert contains(calls[0], pages[0])
    assert contains(calls[1], pages[0]), 'Failed action must retain the prior complete batch'
    assert not contains(calls[1], pages[1]), 'Do not mix a recovery batch with unread pages'
    assert contains(calls[2], pages[1]), 'A successful action must release the next page without notes'
    assert not contains(calls[2], pages[0]), 'Unnoted prior pages must not block progress'
    if not failed_reply['choices'][0]['message']['content']:
        assert ids[0] in snapshots[1]['pending']
        assert ids[0] not in snapshots[1]['exposed']
    else:
        assert ids[0] in snapshots[1]['pending'], 'Recovery requeues a demand without undoing exposure'
        assert ids[0] in snapshots[1]['exposed']
    assert ids[0] not in snapshots[2]['pending']
    assert not session.evidence.notes


def test_final_note_revision_requires_new_http_before_report_and_finish(tmp_path, paper_runtime):
    notes = {topic: f'Model reading note for {topic}: retain the observed claim and page evidence.'
             for topic in ('overview', 'reasoning', 'tool_use', 'multi_agent', 'outlook')}

    def read_and_note(session):
        ids = [eid for eid, item in session.evidence.items.items() if item.page]
        action = ("update_plan(items=[{'title':'read and report','status':'doing'}])\n"
                  "run_command(argv=['python','-m','pytest','-q'])\n"
                  "r=read_file(path='report.json')\n")
        for index, (topic, note) in enumerate(notes.items()):
            action += (f"write_note(title={topic!r}, section={topic!r}, content={note!r}, "
                       f"evidence_ids={[ids[index]]!r})\n")
        return response(code(action))

    updated_note = 'Updated model overview note retaining the observed claim and exact evidence locator.'

    def revise_then_premature_report(session):
        overview = next(eid for eid, item in session.evidence.items.items() if item.page == 1)
        action = (f"write_note(title='overview', section='overview', content={updated_note!r}, evidence_ids={[overview]!r})\n"
                  "write_file(path='report.json',content='{\"premature\":true}',expected_hash=r['file_hash'])")
        return response(code(action))

    session, agent, calls, _, ids = paper_runtime([f'Observed PDF page {n} with substantive text.' for n in range(5)], [
        read_and_note,
        revise_then_premature_report,
        response(code("r=write_file(path='report.json',content='{\"draft\":true}',expected_hash=r['file_hash'])")),
        response(code("r=write_file(path='report.json',content='{\"complete\":true}',expected_hash=r['file_hash'])\n"
                      "run_command(argv=['python','-m','pytest','-q'])\n"
                      "update_plan(items=[{'title':'read and report','status':'done'}])\nfinal_answer('Report verified')")),
    ], verify=True)
    assert agent.run(session.task_prompt()) == 'Report verified'
    assert len(calls) == 4
    assert all(contains(calls[1], note) for note in notes.values())
    assert contains(calls[2], updated_note)
    assert all(contains(calls[2], note) for topic, note in notes.items() if topic != 'overview')
    assert set(ids).issubset(session.evidence.exposed)
    assert session.progress().ready_for_final
    events = [json.loads(line) for line in (tmp_path / 'run/run.log').read_text().splitlines()]
    writes = [i for i, event in enumerate(events) if event['event'] == 'file_write']
    tests = [(i, event['rc']) for i, event in enumerate(events) if event['event'] == 'command_result']
    assert len(writes) == 2
    assert tests[0][0] < writes[0] and tests[0][1] == 1
    assert tests[-1][0] > writes[-1] and tests[-1][1] == 0
    # No reread of the modified report is required before the second write or
    # final verification; its original read is a first-write requirement only.
    assert not any(event['event'] == 'file_read' and i > writes[0]
                   for i, event in enumerate(events))
    errors = [event for event in events if event['event'] == 'agent_error']
    assert len(errors) == 1 and 'overview' in errors[0]['error']
    assert 'Edit prerequisites' in errors[0]['error']



def test_building_views_does_not_acknowledge_delivery_and_note_quote_cannot_hide_page(paper_runtime):
    text = 'A model note may quote an original passage, but quoting does not acknowledge a newly requested PDF page.'
    session, agent, _, _, ids = paper_runtime([text], [response(code("print('unused')"))])
    context, model = session.context, agent.model
    from smolagents.memory import TaskStep
    agent.memory.steps.append(TaskStep(session.task_prompt()))
    before_pending = set(session.evidence.pending)
    first = context.build(agent.memory, model)
    second = context.build(agent.memory, model)
    assert not session.evidence.exposed
    assert set(session.evidence.pending) == before_pending
    assert contains({'messages': [m.dict() for m in first]}, text)
    assert contains({'messages': [m.dict() for m in second]}, text)
    body = {'messages': [m.dict() for m in second]}
    session.evidence.mark_exposed(body, response(code(f'write_note(content={text!r})')), 1)
    session.invoke('write_note', {'title': 'overview', 'section': 'overview',
                                  'content': text, 'evidence_ids': ids})
    session.contract.paper_pages = (1, 2)
    result = {'pages': [{'page': 2, 'text': text}]}
    session.evidence.observe('read_pdf', {}, result)
    new_id = result['evidence_ids'][0]
    messages = context.build(agent.memory, model)
    assert new_id in context.last_manifest['evidence_ids']
    assert contains({'messages': [m.dict() for m in messages]}, session.evidence.render(new_id))
    assert new_id in session.evidence.pending and new_id not in session.evidence.exposed
