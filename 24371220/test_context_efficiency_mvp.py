"""MVP sending-view mechanisms checked through the real SDK MockTransport body."""
import json

import pytest

from course_agent.audit import BudgetExceeded, contains, request_size, strings
from smolagents.memory import ActionStep, TaskStep
from smolagents.monitoring import Timing

from test_paper_delivery import paper_runtime
from test_smolagents import code, response


def status(body):
    marker = 'Course progress before this request (evidence offered below may satisfy pending items after delivery):\n'
    text = next(text for text in strings(body['messages']) if marker in text)
    return json.JSONDecoder().raw_decode(text.split(marker, 1)[1])[0]


def receipt(body):
    marker = 'Paper read receipt (selected, not HTTP-confirmed):\n'
    text = next(text for text in strings(body['messages']) if marker in text)
    return json.JSONDecoder().raw_decode(text.split(marker, 1)[1])[0]


def test_r23_to_r27_does_not_renew_automatic_carry(paper_runtime):
    # Exact original lengths from the documented narrow replay fixture.
    pages = ['R23_PAGE51_' + 'x' * (3844 - len('R23_PAGE51_')),
             'R23_PAGE52_' + 'y' * (4072 - len('R23_PAGE52_'))]
    session, agent, calls, _, ids = paper_runtime(pages, [response(code('print(1)'))] * 5)
    session.contract.max_calls = 40
    session.audit.calls = 22
    agent.memory.steps.append(TaskStep(session.task_prompt()))
    for _ in range(5):
        agent.model.generate(session.context.build(agent.memory, agent.model))
    assert all(contains(body, page) for body in calls[:2] for page in pages)
    assert not any(contains(body, page) for body in calls[2:] for page in pages)
    assert session.evidence.confirmed_anchor[ids[0]] == 23
    assert session.evidence.confirmed_anchor[ids[1]] == 23
    assert not session.evidence.pending
    assert sum(len(page) for page in pages) * len(calls[2:]) == 23748
    assert all(request_size(body)['chars'] <= 32000 for body in calls)


def test_repeated_action_errors_cannot_renew_recovery(paper_runtime):
    pages = [f'ERROR_PAGE_{n}_' + str(n) * 14500 for n in (1, 2, 3)]
    session, agent, calls, snapshots, ids = paper_runtime(pages, [
        response(code("raise ValueError('first failure')")),
        response(code("raise ValueError('second failure')")),
        response(code("print('Continue initial coverage')")),
    ])
    with pytest.raises(BudgetExceeded, match='MAX_STEPS_NO_EXTRA_REQUEST'):
        agent.run(session.task_prompt())
    assert contains(calls[0], pages[0]) and contains(calls[1], pages[0])
    assert not contains(calls[2], pages[0]) and contains(calls[2], pages[1])
    assert ids[0] not in snapshots[1]['pending']
    assert ids[0] not in snapshots[2]['pending']
    assert session.evidence.confirmed_anchor[ids[0]] == 1


def test_coverage_keeps_selected_pages_and_recall_has_independent_block(paper_runtime):
    pages = ['SMALL_RECALL_PAGE_' + 'a' * 500] + [
        f'COVERAGE_PAGE_{n}_' + str(n) * 14500 for n in (2, 3, 4)]
    session, agent, calls, _, ids = paper_runtime(pages, [response(code('print(1)'))] * 3)
    agent.memory.steps.append(TaskStep(session.task_prompt()))
    agent.model.generate(session.context.build(agent.memory, agent.model))
    assert contains(calls[0], pages[0]) and contains(calls[0], pages[1])
    assert not contains(calls[0], pages[2])
    session.invoke('recall_pages', {'pages': [1]})
    agent.model.generate(session.context.build(agent.memory, agent.model))
    assert contains(calls[1], pages[2]), 'Recall cannot remove an admitted unread page'
    assert not contains(calls[1], pages[3]), 'Initial coverage still stops at its blocked page'
    assert contains(calls[1], pages[0]), 'Coverage blocking must not leak into the FIFO recall phase'
    assert receipt(calls[1])['selected_pages'] == [3, 1]
    assert receipt(calls[1])['pending_pages'] == [4]
    assert receipt(calls[1])['pending_coverage_count'] == 1
    assert receipt(calls[1])['pending_explicit_count'] == 0
    assert ids[3] in session.evidence.pending and ids[0] not in session.evidence.pending


def test_zero_progress_and_reserved_receipt_are_present_in_full_request(paper_runtime):
    pages = [f'BUDGET_PAGE_{n}_' + str(n) * 14500 for n in (1, 2)]
    session, agent, calls, _, _ = paper_runtime(pages, [response(code('print(1)'))])
    agent.memory.steps.append(TaskStep(session.task_prompt()))
    agent.memory.steps.append(ActionStep(step_number=0, timing=Timing(start_time=0, end_time=1),
                                        observations='saved output', code_action='print(1)'))
    session.evidence.recent_results.append({'tool': 'save_answer', 'result': {
        'section': 'overview', 'question_id': 'categories', 'saved': True}})
    agent.model.generate(session.context.build(agent.memory, agent.model))
    state = status(calls[0])
    assert state['saved_answers_count'] == '0/10'
    assert sum(len(values) for values in state['missing_answers'].values()) == 10
    assert state['saved_sections_count'] == '0/5' and len(state['missing_sections']) == 5
    assert state['request_number'] == 1 and state['requests_after_response'] == 0
    sent = receipt(calls[0])
    assert sent['selected_pages'] == [1] and sent['selected_count'] == 1
    assert sent['pending_pages'] == [2] and sent['pending_count'] == 1
    assert sent['pending_coverage_count'] == 1 and sent['pending_explicit_count'] == 0
    assert sent['waiting']
    assert contains(calls[0], '"question_id":"categories","saved":true')
    assert request_size(calls[0])['chars'] <= 32000


def test_sent_note_replaces_optional_carry_but_not_explicit_recall(paper_runtime):
    text = 'PAGE_FOR_NOTE_' + 'evidence claim ' * 80
    note = 'Model-authored compact note preserving the observed page claim and locator.'
    session, agent, calls, _, ids = paper_runtime([text], [response(code('print(1)'))] * 3)
    agent.memory.steps.append(TaskStep(session.task_prompt()))
    agent.model.generate(session.context.build(agent.memory, agent.model))
    session.evidence.notes['overview'] = {'id': 'overview', 'content': note,
        'sources': ['paper.pdf'], 'evidence_ids': ids, 'valid': True, 'request': 1}
    agent.model.generate(session.context.build(agent.memory, agent.model))
    assert contains(calls[1], note) and not contains(calls[1], text)
    session.invoke('recall_pages', {'pages': [1]})
    agent.model.generate(session.context.build(agent.memory, agent.model))
    assert contains(calls[2], note) and contains(calls[2], text)


def test_registered_unseen_appendix_is_an_explicit_delivery(paper_runtime):
    session, agent, calls, _, _ = paper_runtime(['MAIN_PAGE_' + 'a' * 100],
                                               [response(code('print(1)'))] * 2)
    agent.memory.steps.append(TaskStep(session.task_prompt()))
    agent.model.generate(session.context.build(agent.memory, agent.model))
    appendix = 'APPENDIX_PAGE_53_' + 'b' * 100
    extracted = {'pages': [{'page': 53, 'text': appendix}]}
    session.evidence.observe('read_pdf', {}, extracted)
    session.invoke('recall_pages', {'pages': [53]})
    agent.model.generate(session.context.build(agent.memory, agent.model))
    assert contains(calls[1], appendix)
    reason = next(value for value in session.context.last_manifest['selection_reasons']
                  if value['id'] == extracted['evidence_ids'][0])
    assert reason['primary'] == 'explicit' and not reason['previously_sent']


def test_successful_answer_survives_later_note_failure_and_one_recovery(paper_runtime):
    page = 'A continuous original passage supplies evidence for a saved answer.'

    def partial_success(session):
        eid = next(eid for eid, item in session.evidence.items.items() if item.page == 1)
        return response(code(
            "save_answer(section='overview', question_id='categories', answer={'value':['answer']}, "
            f"evidence_id={eid!r}, page=1, quote={page!r})\n"
            f"write_note(title='overview', section='overview', content='bad', evidence_ids={[eid]!r})"))

    session, agent, calls, _, _ = paper_runtime([page], [partial_success,
        response(code("print('Repair the failed action only')")), response(code('print(1)'))])
    with pytest.raises(BudgetExceeded, match='MAX_STEPS_NO_EXTRA_REQUEST'):
        agent.run(session.task_prompt())
    assert status(calls[1])['saved_answers_count'] == '1/10'
    assert contains(calls[1], page), 'Partial success does not cancel the one eligible recovery'
    assert not contains(calls[2], session.evidence.render(next(
        eid for eid, item in session.evidence.items.items() if item.page == 1)))
    assert session.evidence.answers['overview']['categories']['answer'] == ['answer']
    events = [json.loads(line) for line in (session.log.output / 'run.log').read_text().splitlines()]
    assert len([event for event in events if event['event'] == 'paper_answer']) == 1


def test_invalidated_answer_is_missing_in_the_next_http_status(paper_runtime):
    page = 'A sufficiently long continuous passage grounds the answer before its PDF version changes.'
    session, agent, calls, _, ids = paper_runtime([page], [response(code('print(1)'))] * 2)
    agent.memory.steps.append(TaskStep(session.task_prompt()))
    agent.model.generate(session.context.build(agent.memory, agent.model))
    session.evidence.save_answer('overview', 'categories', ['answer'], ids[0], 1, page)
    assert 'categories' in session.evidence.answers['overview']
    (session.workspace.repo / 'paper.pdf').write_bytes(b'Changed current PDF version')
    agent.model.generate(session.context.build(agent.memory, agent.model))
    state = status(calls[1])
    assert state['saved_answers_count'] == '0/10'
    assert 'categories' in state['missing_answers']['overview']
    assert sum(len(values) for values in state['missing_answers'].values()) == 10
    assert not session.evidence.items[ids[0]].valid
