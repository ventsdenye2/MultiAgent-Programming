"""Offline checks for the optional static prompt presentation."""
import ast
import inspect
import json

import pytest
from test_smolagents import CONFIG, make_session
from smolagents import Tool
import httpx

from course_agent.audit import AuditedOpenAIModel, RequestAudit
from course_agent.context import EvidenceContext
from course_agent.engine import make_agent
from course_agent.policy import load_task
from course_agent.recording import RunLog
from course_agent.session import CourseSession


class ExtraTool(Tool):
    name = 'extra_example'
    description = 'Unknown tool full fallback sentinel.'
    inputs = {'value': {'type': 'string', 'description': 'A special value.'}}
    output_type = 'string'

    def forward(self, value: str) -> str:
        return value


def make_paper_session(root, compact, text):
    repo = root / 'repo'
    repo.mkdir()
    (repo / 'paper.json').write_text(json.dumps({'required_pages': [1, 2]}), encoding='utf-8')
    (repo / 'report.json').write_text('{}', encoding='utf-8')
    cfg = CONFIG | {'static_context_compact': compact}
    contract = load_task(text, repo, cfg, 'paper')
    log = RunLog(root / 'run')
    session = CourseSession(contract, root / 'run', log, cfg)
    audit = RequestAudit(contract, log, session.evidence)
    model = AuditedOpenAIModel(cfg, audit, 'offline', transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    context = EvidenceContext(session)
    session.context, session.audit = context, audit
    agent = make_agent(model, session, context)
    return session, context, agent, model, log


@pytest.mark.parametrize('profile', ['source', 'paper'])
@pytest.mark.parametrize('structured', [True, False])
def test_compact_actual_agent_tools_and_original_task(tmp_path, profile, structured):
    runtimes = []
    for compact in (False, True):
        root = tmp_path / str(compact)
        root.mkdir()
        text = '原题全文：第一行\n第二行。\n'
        if profile == 'paper':
            session, _, agent, model, log = make_paper_session(root, compact, text)
        else:
            session, _, agent, model, log = make_session(root, profile, {'static_context_compact': compact}, text=text)
        agent._use_structured_outputs_internally = structured
        # Exercise the same template selection used by make_agent with both protocols.
        from course_agent.prompts import course_prompt_templates
        agent.prompt_templates = course_prompt_templates(structured, compact)
        agent.tools['extra_example'] = ExtraTool()
        runtimes.append((session, agent, model, log))
    try:
        base, compact = runtimes
        baseline, reduced = base[1].system_prompt, compact[1].system_prompt
        assert len(reduced) + len(compact[0].task_prompt()) < len(baseline) + len(base[0].task_prompt())
        assert compact[0].task_prompt().startswith(compact[0].contract.text + '\n\n')
        for name in compact[1].tools:
            assert name in reduced
        assert compact[1].tools['extra_example'].to_code_prompt() in reduced
        tool_block = reduced.split('Available tools:\n```python', 1)[1].split('```', 1)[0]
        definitions = {node.name: node for node in ast.parse(tool_block).body if isinstance(node, ast.FunctionDef)}
        for name, tool in compact[1].tools.items():
            if not hasattr(tool, 'call_signature'):
                continue
            node = definitions[name]
            assert [arg.arg for arg in node.args.args] == list(tool.call_signature.parameters)
            defaults = [ast.literal_eval(value) for value in node.args.defaults]
            expected = [p.default for p in tool.call_signature.parameters.values()
                        if p.default is not inspect.Parameter.empty]
            assert defaults == expected
            type_names = {'string': 'str', 'integer': 'int', 'number': 'float', 'boolean': 'bool',
                          'array': 'list', 'object': 'dict'}
            for arg in node.args.args:
                schema = tool.parameters['properties'][arg.arg]
                assert arg.annotation.id == type_names.get(schema.get('type'), 'object')
                assert json.dumps(schema, ensure_ascii=False, separators=(',', ':')) in ast.get_docstring(node)
            assert node.returns.id == 'dict'
            assert tool.description in ast.get_docstring(node)
        for term in ('final_answer', 'current-version verification', 'baseline or report'):
            assert term in reduced
        assert ('ONE JSON object' if structured else 'ONE fenced Python block') in reduced
        docs = '\n'.join(ast.get_docstring(node) or '' for node in definitions.values())
        assert ('old_text' in docs and 'new_text' in docs and 'nonoverlapping' in docs) if profile == 'source' else (
            all(term in docs for term in ('pages (list of {page,text})',
                                         "{'value': string, integer or list of strings}",
                                         'before_hash', 'sources, chars')))
    finally:
        for _, _, model, log in runtimes:
            model.close()
            log.close()


def test_default_is_baseline(tmp_path):
    session, _, agent, model, log = make_session(tmp_path, 'source')
    try:
        from course_agent.prompts import SYSTEM, JSON_PROTOCOL
        assert not session.static_context_compact
        assert agent.prompt_templates['system_prompt'] == SYSTEM.replace('__OUTPUT_PROTOCOL__', JSON_PROTOCOL)
        assert 'Tools return Python dicts; use their file_hash' in session.task_prompt()
    finally:
        model.close()
        log.close()
