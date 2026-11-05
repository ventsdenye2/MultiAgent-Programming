"""Paper page recall through the existing Python and DSML execution paths."""
import json

import pytest
import course_agent  # Configure the vendored smolagents import path.
from smolagents.models import ChatMessage, MessageRole

from test_protocol import dsml, invoke
from test_static_context import make_paper_session


@pytest.mark.parametrize('protocol', ['python', 'dsml'])
def test_recall_pages_executor_and_audit(tmp_path, protocol):
    session, _, agent, model, log = make_paper_session(tmp_path, False, 'Read paper.')
    try:
        (tmp_path / 'repo/paper.pdf').write_text('version')
        version = session.workspace.current_hash('paper.pdf')
        ids = [session.evidence._add('paper.pdf', version, f'page:{n}', f'Page {n}', page=n)
               for n in (1, 2)]
        agent.python_executor.send_tools(agent.tools)
        if protocol == 'dsml':
            raw = dsml(invoke('recall_pages', pages=[2, 1, 2]))
            adapted = model.protocol_adapter.adapt(ChatMessage(role=MessageRole.ASSISTANT, content=raw))
            code = json.loads(adapted.content)['code']
        else:
            code = 'recall_pages(pages=[2, 1, 2])'
        agent.python_executor(code)
        assert session.evidence.pending == [ids[1], ids[0]]
        assert not session.evidence.exposed
        events = [json.loads(line) for line in (log.output / 'run.log').read_text(encoding='utf-8').splitlines()]
        assert any(e['event'] == 'tool_call' and e['tool'] == 'recall_pages'
                   and e['arguments'] == {'pages': [2, 1, 2]} for e in events)
        assert any(e['event'] == 'tool_result' and e['action']['tool'] == 'recall_pages'
                   and e['result']['requested_count'] == 2 for e in events)
        with pytest.raises(Exception):
            agent.python_executor('recall_pages(pages=[1, True])')
        assert session.evidence.pending == [ids[1], ids[0]]
    finally:
        model.close()
        log.close()


def test_recall_pages_schema_is_paper_only(tmp_path):
    session, _, _, model, log = make_paper_session(tmp_path, False, 'Read paper.')
    try:
        tool = next(t for t in session.tools() if t.name == 'recall_pages')
        assert tool.parameters['required'] == ['pages']
        assert tool.parameters['properties']['pages']['items'] == {'type': 'integer'}
        session.contract.profile = 'source'
        assert 'recall_pages' not in {t.name for t in session.tools()}
    finally:
        model.close()
        log.close()
