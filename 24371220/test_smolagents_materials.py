"""Offline capacity/provenance checks using the actual course source and PDF."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

from course_agent.audit import contains
from course_agent.policy import load_task
from course_agent.recording import RunLog
from course_agent.session import CourseSession
from course_agent.context import EvidenceContext
from course_agent.engine import make_agent
from course_agent.audit import AuditedOpenAIModel, RequestAudit
from smolagents.memory import ActionStep, TaskStep
from smolagents.monitoring import Timing
from smolagents.utils import AgentExecutionError
import httpx

from test_smolagents import CONFIG, response, code


MATERIALS = Path(os.environ.get('COURSE_MATERIALS', Path(__file__).resolve().parents[3] / 'materials/long-context'))


@pytest.fixture
def build_session(tmp_path):
    resources = []
    def build(profile, repo, task):
        cfg = CONFIG | {'read_only': False, 'max_steps': 40}
        if profile == 'generic':
            cfg['read_only'] = True
        spec = load_task(task, repo, cfg, profile)
        spec.verify_commands = []  # This suite tests capacity; command execution is tested separately.
        log = RunLog(tmp_path / 'run')
        session = CourseSession(spec, tmp_path / 'run', log, cfg)
        audit = RequestAudit(spec, log, session.evidence)
        model = AuditedOpenAIModel(cfg, audit, 'offline', transport=httpx.MockTransport(lambda r: httpx.Response(500)))
        context = EvidenceContext(session)
        session.context, session.audit = context, audit
        agent = make_agent(model, session, context)
        agent.memory.steps.append(TaskStep(session.task_prompt()))
        session.invoke('update_plan', {'items': [{'title': 'read, implement, verify', 'status': 'doing'}]})
        resources.append((model, log))
        return session, context, agent, model
    yield build
    for model, log in resources:
        model.close()
        log.close()


def test_real_three_file_preedit_coverage_and_source_notes(tmp_path, build_session):
    source = MATERIALS / '公开任务/题目2'
    repo = tmp_path / 'repo'
    repo.mkdir()
    targets = ['deepinfer/environ.py', 'deepinfer/logger.py', 'deepinfer/engine/stats_logger.py']
    with tarfile.open(source / 'DeepInfer-774ce244.tar.gz') as archive:
        for rel in targets:
            member = next(m for m in archive.getmembers() if m.name.endswith('/' + rel))
            target = repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
    task = (source / 'task.md').read_text(encoding='utf-8')
    session, context, agent, model = build_session('source', repo, task)
    for rel in targets:
        session.invoke('read_file', {'path': rel})
    assert sum(len((repo / rel).read_text()) for rel in targets) > 30000
    with pytest.raises(ValueError, match='Edit prerequisites'):
        session._before_write({'path': targets[0]})
    all_ids = set(session.evidence.items)
    for number in range(1, 15):
        messages = context.build(agent.memory, model)
        assert model.estimate(messages) <= 32000
        body = {'messages': [m.dict() for m in messages]}
        session.evidence.mark_exposed(body, response(code('print(1)')), number)
        for rel in targets:
            ids = sorted(session.evidence.required[rel])
            if set(ids).issubset(session.evidence.exposed) and rel not in session.evidence.notes:
                content = 'Model note describing the complete mechanisms in ' + rel + ' and their cross-module interfaces.'
                session.evidence.last_response = response(code(f'write_note(title={rel!r}, content={content!r}, evidence_ids={ids!r})'))
                session.invoke('write_note', {'title': rel, 'content': content, 'evidence_ids': ids})
        if not session.evidence.missing():
            break
    assert all_ids.issubset(session.evidence.exposed)
    assert not session.evidence.missing()
    session._before_write({'path': targets[0]})
    # Direct reuse can satisfy the gate in the first request. Separately verify
    # that the subsequent view reuses the newly written notes instead.
    messages = context.build(agent.memory, model)
    body = {'messages': [m.dict() for m in messages]}
    session.evidence.mark_exposed(body, response(code('print(1)')), number + 1)
    assert not session.evidence.missing()
    assert all(contains(body, note['content']) for note in session.evidence.notes.values())
    # Full original records remain intact even though selected sending view is smaller.
    for rel in targets:
        before = len(session.evidence.items)
        session.invoke('read_file', {'path': rel})
        assert len(session.evidence.items) == before
    (repo / targets[0]).write_text((repo / targets[0]).read_text() + '\n# version changed\n')
    session.evidence.refresh()
    assert not session.evidence.notes[targets[0]]['valid']
    assert not session.evidence.source_reused(targets[0])


def test_real_pdf_52_pages_fit_batched_and_five_notes_reused(tmp_path, build_session):
    assert shutil.which('pdftotext'), 'Run this course test in WSL with poppler-utils installed'
    source = MATERIALS / '公开任务/题目1'
    repo = tmp_path / 'repo'
    repo.mkdir()
    for name in ('paper.pdf', 'paper.json', 'read_pdf.py', 'report.json'):
        shutil.copy2(source / 'repo' / name, repo / name)
    task = (source / 'task.md').read_text(encoding='utf-8')
    session, context, agent, model = build_session('paper', repo, task)
    session.invoke('read_file', {'path': 'report.json'})
    session.invoke('read_pdf', {'start_page': 1, 'end_page': 52})
    page_ids = [eid for eid, e in session.evidence.items.items() if e.page]
    assert len(page_ids) == 52
    assert sum(len(session.evidence.items[eid].text) for eid in page_ids) > 100000
    session.evidence.recall(page_ids, 12000)
    seen = set()
    sizes = []
    for number in range(1, 36):
        messages = context.build(agent.memory, model)
        sizes.append(model.estimate(messages))
        body = {'messages': [m.dict() for m in messages]}
        session.evidence.mark_exposed(body, response(code('print(1)')), number)
        seen |= session.evidence.current
        if set(page_ids).issubset(seen):
            break
    assert set(page_ids).issubset(seen), {'missing': len(set(page_ids) - seen), 'sizes': sizes}
    assert max(sizes) <= 32000
    for i, topic in enumerate(session.contract.topics):
        content = 'A simulated reading note for ' + topic + ', based on the actual exposed PDF text and page provenance.'
        session.evidence.last_response = response(code(f'write_note(content={content!r})'))
        session.invoke('write_note', {'title': topic, 'section': topic, 'content': content,
                                     'evidence_ids': [page_ids[i]]})
    messages = context.build(agent.memory, model)
    body = {'messages': [m.dict() for m in messages]}
    session.evidence.mark_exposed(body, response(code('print(1)')), number + 1)
    assert not session.evidence.missing()
    assert all(contains(body, n['content']) for n in session.evidence.notes.values())
    (tmp_path / 'capacity.json').write_text(json.dumps({
        'required_pages': 52, 'pages_exposed': len(set(page_ids) & seen),
        'reading_requests_simulated': number, 'max_body_chars': max(sizes),
        'five_notes_reused': True, 'provider_calls': 0}, indent=2))


def test_large_source_cannot_evict_latest_error(tmp_path, build_session):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'data.txt').write_text('SOURCE_' + 'a' * 15000)
    # Generic read-only semantics avoid task-specific edit requirements in this test.
    session, context, agent, model = build_session('generic', repo, 'Only read this material; do not edit.')
    session.invoke('read_file', {'path': 'data.txt'})
    error = 'CURRENT_FAILURE: required cross-file source still missing'
    agent.memory.steps.append(ActionStep(step_number=1, timing=Timing(start_time=0, end_time=1),
                                        code_action='read_file(path="data.txt")',
                                        observations=(repo / 'data.txt').read_text(),
                                        error=AgentExecutionError(error, agent.logger)))
    messages = context.build(agent.memory, model)
    assert contains({'messages': [m.dict() for m in messages]}, error)
    assert model.estimate(messages) <= 32000
