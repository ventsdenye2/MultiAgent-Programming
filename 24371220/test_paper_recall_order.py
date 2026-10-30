"""HTTP regression: explicit paper recalls are queued, then delivered FIFO."""
from smolagents.memory import TaskStep

from course_agent.audit import contains, request_size
from test_paper_delivery import paper_runtime
from test_smolagents import code, response


def test_recall_order_after_initial_coverage(paper_runtime):
    pages = [f'PAGE_{n:02d}_' + str(n % 10) * (13000 if n in {11, 12, 13, 52} else 100)
             for n in range(1, 53)]
    replies = [response(code('print(1)')) for _ in range(20)]
    session, agent, calls, _, ids = paper_runtime(pages, replies)
    agent.memory.steps.append(TaskStep(session.task_prompt()))
    model = agent.model
    while not set(ids).issubset(session.evidence.exposed):
        model.generate(session.context.build(agent.memory, model))
        assert len(calls) < 15
    result = session.invoke('recall', {'evidence_ids': [ids[51], ids[10], ids[11], ids[12]]})
    assert result['requested'][0]['locator'] == 'page:52'
    assert result['queued_count'] == 4 and 'not delivered' in result['message']
    before = len(calls)
    while session.evidence.pending:
        model.generate(session.context.build(agent.memory, model))
        assert len(calls) < 20
    recalled = calls[before:]
    assert contains(recalled[0], pages[51])
    assert not contains(recalled[0], pages[10])
    assert all(any(contains(body, pages[n - 1]) for body in recalled) for n in (11, 12, 13))
    assert all(request_size(body)['chars'] <= 32000 for body in calls)
