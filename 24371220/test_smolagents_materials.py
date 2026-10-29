"""Offline capacity/provenance checks using the actual course source and PDF."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

from course_agent.audit import contains, strings
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

from test_smolagents import CONFIG, response, code, run_script


MATERIALS = Path(os.environ.get('COURSE_MATERIALS', Path(__file__).resolve().parents[3] / 'materials/long-context'))


@pytest.fixture
def build_session(tmp_path):
    resources = []
    def build(profile, repo, task):
        cfg = CONFIG | {'read_only': False, 'max_steps': 40, 'use_structured_outputs_internally': False}
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
        agent = make_agent(model, session, context, use_structured_outputs_internally=False)
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
    # Unsummarized mechanisms remain available in consecutive requests. The
    # previous implementation oscillated between sources: being present in
    # the previous HTTP body incorrectly made them optional in the next one.
    for number in range(1, 4):
        messages = context.build(agent.memory, model)
        body = {'messages': [m.dict() for m in messages]}
        session.evidence.mark_exposed(body, response(code('print(1)')), number)
        assert all_ids.issubset(session.evidence.current)
        assert not session.evidence.missing()
        assert not context.last_manifest['deferred']
    # A requested range containing a mechanism should not duplicate that
    # mechanism as another evidence block in the sending view.
    item = next(item for item in session.evidence.items.values()
                if item.source == 'deepinfer/logger.py' and 'class NewLineFormatter' in item.text)
    start, end = map(int, item.locator.removeprefix('lines:').split('-'))
    session.invoke('read_range', {'path': item.source, 'start_line': start, 'end_line': end + 1})
    messages = context.build(agent.memory, model)
    body = {'messages': [m.dict() for m in messages]}
    assert sum(text.count(item.text) for msg in messages for text in strings(msg.content)) == 1
    session.evidence.mark_exposed(body, response(code('print(1)')), 4)
    assert not session.evidence.pending
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
    # A new read explicitly asks for the same originals even though valid
    # notes already represent them. Only actual HTTP delivery clears demand.
    requested = set(session.evidence.pending)
    assert requested == all_ids
    messages = context.build(agent.memory, model)
    session.evidence.mark_exposed({'messages': []}, response(code('print(1)')), number + 2)
    assert set(session.evidence.pending) == requested
    delivered = set()
    for replay_number in range(number + 3, number + 10):
        messages = context.build(agent.memory, model)
        body = {'messages': [m.dict() for m in messages]}
        session.evidence.mark_exposed(body, response(code('print(1)')), replay_number)
        delivered |= session.evidence.current & requested
        assert all(contains(body, note['content']) for note in session.evidence.notes.values())
        if not session.evidence.pending:
            break
    assert delivered == requested
    assert not session.evidence.pending
    # A real failed action re-read all files and then requested enclosing edit
    # ranges. Deliver the ranges once, covering their contained mechanisms;
    # queue order must not spend the budget on duplicates and starve the ranges.
    cross_note = 'Offline cross-module note preserving complete observed interfaces. '.ljust(2500, '.')
    session.evidence.last_response = response(code(f'write_note(content={cross_note!r})'))
    session.invoke('write_note', {'title': 'cross_module', 'content': cross_note, 'evidence_ids': sorted(all_ids)})
    for rel in targets:
        session.invoke('read_file', {'path': rel})
    ranges = [session.invoke('read_range', {'path': 'deepinfer/logger.py', 'start_line': 33, 'end_line': 220}),
              session.invoke('read_range', {'path': 'deepinfer/environ.py', 'start_line': 1, 'end_line': 120})]
    messages = context.build(agent.memory, model)
    body = {'messages': [m.dict() for m in messages]}
    assert all(contains(body, r['content']) for r in ranges)
    session.evidence.mark_exposed(body, response(code('print(1)')), replay_number + 1)
    assert not session.evidence.pending
    assert not session.evidence.missing()
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
    full_notes_before_last_page = False
    for number in range(1, 36):
        messages = context.build(agent.memory, model)
        sizes.append(model.estimate(messages))
        body = {'messages': [m.dict() for m in messages]}
        session.evidence.mark_exposed(body, response(code('print(1)')), number)
        seen |= session.evidence.current
        # A successful reading action advances to new pages without a per-page
        # note gate. Only the final five topic notes are required by the course.
        delivered_pages = {eid for eid in session.evidence.current if eid in page_ids}
        assert delivered_pages
        agent.memory.steps.append(ActionStep(
            step_number=number, timing=Timing(start_time=0, end_time=1),
            code_action='print("Read this PDF batch.")', observations='Read this PDF batch.'))
        if number % 2 == 0:
            topic = session.contract.topics[(number // 2 - 1) % 5]
            content = ('Model note for ' + topic + '; keep observed claims and evidence locators. ').ljust(1500, '.')
            session.evidence.last_response = response(code(f'write_note(content={content!r})'))
            # One observed page grounds this note; other pages do not need a
            # per-page acknowledgement before the next original batch advances.
            session.invoke('write_note', {'title': topic, 'section': topic, 'content': content,
                                          'evidence_ids': [sorted(delivered_pages)[0]]})
        if len(session.evidence.notes) == 5 and not set(page_ids).issubset(seen):
            full_notes_before_last_page = True
        if set(page_ids).issubset(seen):
            break
    assert set(page_ids).issubset(seen), {'missing': len(set(page_ids) - seen), 'sizes': sizes}
    assert full_notes_before_last_page, 'Exercise remaining originals with all five maximum-size notes retained'
    assert number <= 30, 'Reserve at least ten requests for setup, report delivery and verification'
    note_tool = next(tool for tool in session.tools() if tool.name == 'write_note')
    assert 'section' in note_tool.parameters['required']
    with pytest.raises(ValueError, match='20..1500'):
        session.evidence.write_note('too long', 'x' * 1501, [page_ids[0]], section='overview')
    with pytest.raises(ValueError, match='20..1500'):
        session.evidence.write_note('too long', 'x' * 1501, [page_ids[0]])
    assert max(sizes) <= 32000
    for i, topic in enumerate(session.contract.topics):
        content = ('A simulated reading note for ' + topic + ', based on the actual exposed PDF text and page provenance.').ljust(1500, '.')
        session.evidence.last_response = response(code(f'write_note(content={content!r})'))
        session.invoke('write_note', {'title': topic, 'section': topic, 'content': content,
                                     'evidence_ids': [page_ids[i]]})
    messages = context.build(agent.memory, model)
    body = {'messages': [m.dict() for m in messages]}
    session.evidence.mark_exposed(body, response(code('print(1)')), number + 1)
    assert not session.evidence.missing()
    assert all(len(n['content']) == 1500 and contains(body, n['content'])
               for n in session.evidence.notes.values())
    (tmp_path / 'capacity.json').write_text(json.dumps({
        'required_pages': 52, 'pages_exposed': len(set(page_ids) & seen),
        'reading_requests_simulated': number, 'max_body_chars': max(sizes),
        'five_notes_reused': True, 'provider_calls': 0}, indent=2))


def test_recorded_source_note_uses_source_limit_and_source_log_event(tmp_path, build_session):
    archived = Path(__file__).resolve().parent / 'experiments/smolagents/smolagents-20261029-095013-395938'
    events = [json.loads(line) for line in
              (archived / 'source/development/run.log').read_text(encoding='utf-8').splitlines()]
    repo = tmp_path / 'repo'
    repo.mkdir()
    for event in events:
        if event['event'] == 'snapshot':
            target = repo / event['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(event['content'], encoding='utf-8')
    task = (MATERIALS / '公开任务/题目2/task.md').read_text(encoding='utf-8')
    session, context, agent, model = build_session('source', repo, task)
    args = next(e['arguments'] for e in events if e['event'] == 'tool_call' and e['tool'] == 'write_note')
    assert args['section'] == 'mechanisms' and 1500 < len(args['content']) <= 3000
    for rel in sorted(session.contract.required_reads):
        session.invoke('read_file', {'path': rel})
    # Deliver the original sources through the real selector. The note text is
    # exactly the historical model output; this is an offline validation only.
    payload = next(e['response'] for e in events if e['event'] == 'model_response' and e['number'] == 10)
    for number in range(1, 10):
        messages = context.build(agent.memory, model)
        session.evidence.mark_exposed({'messages': [m.dict() for m in messages]}, payload, number)
        if set(args['evidence_ids']).issubset(session.evidence.exposed):
            break
    assert set(args['evidence_ids']).issubset(session.evidence.exposed)
    note_tool = next(tool for tool in session.tools() if tool.name == 'write_note')
    assert note_tool.inputs['section']['nullable']
    note_tool(**args)
    trace = [json.loads(line) for line in (tmp_path / 'run/run.log').read_text().splitlines()]
    notes = [e for e in trace if e['event'] == 'context_note']
    assert len(notes) == 1 and notes[0]['content'] == args['content']
    assert set(notes[0]['sources']) == session.contract.required_reads
    assert not any(e['event'] == 'section_note' for e in trace)
    messages = context.build(agent.memory, model)
    assert contains({'messages': [m.dict() for m in messages]}, args['content'])


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



def test_real_source_first_write_directly_reuses_mechanisms_without_notes(tmp_path):
    targets = ['deepinfer/environ.py', 'deepinfer/logger.py', 'deepinfer/engine/stats_logger.py']

    def setup(repo):
        with tarfile.open(MATERIALS / '公开任务/题目2/DeepInfer-774ce244.tar.gz') as archive:
            for rel in targets:
                member = next(m for m in archive.getmembers() if m.name.endswith('/' + rel))
                target = repo / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
        (repo / 'test_offline.py').write_text('def test_fixture():\n    assert True\n')

    read = ("update_plan(items=[{'title':'verify source delivery','status':'doing'}])\n"
            "run_command(argv=['python','-m','pytest','-q'])\n")
    write = ''
    for index, rel in enumerate(targets):
        read += f"r{index}=read_file(path={rel!r})\n"
        write += (f"write_file(path={rel!r},content=r{index}['content']+'\\n# Offline delivery regression.\\n',"
                  f"expected_hash=r{index}['file_hash'])\n")
    write += ("run_command(argv=['python','-m','pytest','-q'])\n"
              "update_plan(items=[{'title':'verify source delivery','status':'done'}])\n"
              "final_answer('Direct source reuse verified')")
    rc, result, calls, events = run_script(tmp_path, [read, write],
        {'read_only': False, 'editable': targets}, profile='source', setup=setup)
    assert rc == 0, result
    assert len(calls) == 2
    assert not any(event['event'] == 'context_note' for event in events)
    writes = [(i, event) for i, event in enumerate(events) if event['event'] == 'file_write']
    assert len(writes) == 3
    first_write = writes[0][0]
    for rel in targets:
        assert any(event['event'] == 'file_read' and event['path'] == rel and i < first_write
                   for i, event in enumerate(events))
    assert not any(event['event'] == 'agent_error' for event in events)



def _source_working_set_fixture(tmp_path, build_session, oversized=False):
    repo = tmp_path / 'source-working-set'
    repo.mkdir()
    targets = ['deepinfer/environ.py', 'deepinfer/logger.py', 'deepinfer/engine/stats_logger.py']
    with tarfile.open(MATERIALS / '公开任务/题目2/DeepInfer-774ce244.tar.gz') as archive:
        for rel in targets:
            member = next(m for m in archive.getmembers() if m.name.endswith('/' + rel))
            target = repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
    if oversized:
        logger = repo / 'deepinfer/logger.py'
        logger.write_text(logger.read_text() + '\n# ' + 'Oversized surrounding comment. ' * 2000 + '\n')
    task = (MATERIALS / '公开任务/题目2/task.md').read_text(encoding='utf-8')
    session, context, agent, model = build_session('source', repo, task)
    for rel in targets:
        session.invoke('read_file', {'path': rel})
    return session, context, agent, model


def test_source_surrounding_ranges_remain_across_turns_and_expire_with_version(tmp_path, build_session):
    session, context, agent, model = _source_working_set_fixture(tmp_path, build_session)
    required = set().union(*session.evidence.required.values())
    messages = context.build(agent.memory, model)
    session.evidence.mark_exposed({'messages': [m.dict() for m in messages]}, response(code('print(1)')), 1)
    assert required.issubset(session.evidence.current)
    ranges = [session.invoke('read_range', {'path': 'deepinfer/environ.py', 'start_line': 95, 'end_line': 230})]
    messages = context.build(agent.memory, model)
    session.evidence.mark_exposed({'messages': [m.dict() for m in messages]}, response(code('print(2)')), 2)
    for path, start, end in [('deepinfer/environ.py', 1, 30),
                             ('deepinfer/logger.py', 1, 32), ('deepinfer/logger.py', 69, 96)]:
        ranges.append(session.invoke('read_range', {'path': path, 'start_line': start, 'end_line': end}))
    for number in (3, 4):
        messages = context.build(agent.memory, model)
        body = {'messages': [m.dict() for m in messages]}
        assert model.estimate(messages) <= 32000
        assert all(contains(body, item['content']) for item in ranges)
        assert all(contains(body, session.evidence.items[eid].text) for eid in required)
        # A containing range replaces a complete mechanism rather than adding
        # a second copy; mechanisms not fully contained remain independently.
        assert all(sum(text.count(session.evidence.items[eid].text)
                       for msg in messages for text in strings(msg.content)) == 1 for eid in required)
        session.evidence.mark_exposed(body, response(code(f'print({number})')), number)
        assert required.issubset(session.evidence.current)
        assert not session.evidence.pending
    old_ids = {eid for item in ranges if item['path'] == 'deepinfer/environ.py' for eid in item['evidence_ids']}
    environ = session.contract.repo / 'deepinfer/environ.py'
    environ.write_text(environ.read_text() + '\n# New source version.\n')
    session.evidence.refresh()
    assert all(not session.evidence.items[eid].valid for eid in old_ids)
    messages = context.build(agent.memory, model)
    assert not old_ids.intersection(context.last_manifest['evidence_ids'])
    assert not session.evidence.source_reused('deepinfer/environ.py')


def test_oversized_surrounding_range_cannot_evict_required_source_mechanisms(tmp_path, build_session):
    session, context, agent, model = _source_working_set_fixture(tmp_path, build_session, oversized=True)
    required = set().union(*session.evidence.required.values())
    messages = context.build(agent.memory, model)
    session.evidence.mark_exposed({'messages': [m.dict() for m in messages]}, response(code('print(1)')), 1)
    logger = session.contract.repo / 'deepinfer/logger.py'
    surrounding = session.invoke('read_range', {'path': 'deepinfer/logger.py', 'start_line': 1,
                                               'end_line': len(logger.read_text().splitlines())})
    assert len(surrounding['content']) > 32000
    for number in (2, 3):
        messages = context.build(agent.memory, model)
        body = {'messages': [m.dict() for m in messages]}
        assert model.estimate(messages) <= 32000
        assert all(contains(body, session.evidence.items[eid].text) for eid in required)
        assert not contains(body, surrounding['content'])
        assert set(surrounding['evidence_ids']).issubset(session.evidence.pending)
        session.evidence.mark_exposed(body, response(code(f'print({number})')), number)
        assert required.issubset(session.evidence.current)
        assert set(surrounding['evidence_ids']).issubset(session.evidence.pending)
