"""Independent offline review of structured output and official final checks."""
import json
from types import SimpleNamespace

import httpx
import pytest

from course_agent.cli import execute
from course_agent.evidence import EvidenceStore, PAPER_QUESTIONS
from course_agent.policy import TaskContract
from course_agent.workspace import WorkspaceTools
from course_agent.session import CourseSession
from test_smolagents import CONFIG, code, response


def test_saved_answer_detaches_mutable_model_list(tmp_path):
    (tmp_path / 'paper.pdf').write_text('version')
    ws = WorkspaceTools(tmp_path, tmp_path, set(), lambda *a, **k: None)
    contract = SimpleNamespace(profile='paper', topics=tuple(PAPER_QUESTIONS), paper_pages=(1,))
    store = EvidenceStore(contract, ws, lambda *a, **k: None)
    quote = 'A continuous quotation with enough characters.'
    eid = store._add('paper.pdf', ws.current_hash('paper.pdf'), 'page:1', quote, page=1)
    store.exposed.add(eid)
    answer = ['model generated choice']
    store.save_answer('overview', 'categories', answer, eid, 1, quote)
    answer[0] = 'later mutation'
    answer.append('another value')
    assert store.answers['overview']['categories']['answer'] == ['model generated choice']


def test_latest_failed_verification_revokes_older_success(tmp_path):
    (tmp_path / 'calc.py').write_text('answer = 42\n')
    spec = TaskContract('Verify calc.py.', tmp_path, 'source', {'calc.py'}, max_calls=6)
    session = CourseSession(spec, tmp_path / 'out', lambda *a, **k: None, CONFIG)
    args = {'argv': ['python', '-m', 'pytest', '-q']}
    result = {'rc': 0, 'stdout': '1 passed in 0.01s', 'stderr': '', 'timed_out': False}
    versions = session.versions()
    session._record_command(args, result, versions)
    assert not session.progress().verification_missing
    session._record_command(args, dict(result, rc=1, stdout='1 failed in 0.01s'), versions)
    assert session.progress().verification_missing
    assert session.last_test['versions'] == versions
    assert session.last_test['rc'] == 1
    (tmp_path / 'calc.py').write_text('answer = 43\n')
    session._record_command(args, result, versions)
    assert session.progress().verification_missing


def run_final_check(tmp_path, outputs):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'calc.py').write_text('answer = 0\n')
    (repo / 'test_calc.py').write_text('from calc import answer\ndef test_answer():\n    assert answer == 42\n')
    out = tmp_path / 'run'
    cfg = CONFIG | {'read_only': False, 'max_steps': 6}
    # A minimal source-profile fixture isolates final-check behavior; no source
    # reading obligations are being asserted by these tests.
    spec = TaskContract('Fix calc.py and verify.', repo, 'source', {'calc.py'}, max_calls=6)
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=response(code(outputs[len(calls)-1])))
    rc, result = execute(spec, cfg, out, transport=httpx.MockTransport(handler), api_key='offline-test')
    events = [json.loads(line) for line in (out / 'run.log').read_text().splitlines()]
    memory = json.loads((out / 'memory.json').read_text())
    return rc, result, calls, events, memory


def start(value):
    return "update_plan(items=[{'title':'fix and verify','status':'doing'}])\n" + \
        "run_command(argv=['python','-m','pytest','-q'])\nr=read_file(path='calc.py')\n" + \
        f"write_file(path='calc.py', content='answer = {value}\\n', expected_hash=r['file_hash'])\n"


def test_official_final_check_runs_current_verification_and_records_success(tmp_path):
    rc, result, calls, events, memory = run_final_check(tmp_path, [start(42), "final_answer('finished')"])
    assert rc == 0, result
    assert len(calls) == 2
    assert [e['rc'] for e in events if e['event'] == 'command_result'] == [1, 0]
    assert any(e['event'] == 'agent_step' and e['step'].get('is_final_answer') for e in events)
    assert any(step.get('is_final_answer') for step in memory)
    assert result['remaining'] == []


def test_official_final_check_failure_recovers_after_model_repairs(tmp_path):
    repair = "r=read_file(path='calc.py')\nwrite_file(path='calc.py', content='answer = 42\\n', expected_hash=r['file_hash'])\nfinal_answer('repaired')"
    rc, result, calls, events, memory = run_final_check(tmp_path, [start(41), "final_answer('premature')", repair])
    assert rc == 0, result
    assert len(calls) == 3
    assert [e['rc'] for e in events if e['event'] == 'command_result'] == [1, 1, 0]
    assert any(e['event'] == 'agent_error' and 'Verification failed' in e['error'] for e in events)
    assert any(step.get('is_final_answer') for step in memory)


def test_official_final_check_cannot_accept_no_written_artifact(tmp_path):
    rc, result, calls, events, memory = run_final_check(tmp_path, [
        "update_plan(items=[{'title':'fix and verify','status':'done'}])\nrun_command(argv=['python','-m','pytest','-q'])\nfinal_answer('no artifact')",
        start(42), "final_answer('repaired')"])
    assert rc == 0, result
    assert len(calls) == 3
    assert any(e['event'] == 'agent_error' and 'calc.py' in e['error'] for e in events)
    assert sum(bool(step.get('is_final_answer')) for step in memory) == 1


def test_successful_write_survives_later_statement_error(tmp_path):
    rc, result, calls, events, memory = run_final_check(tmp_path, [
        start(42) + "print(1 / 0)\nfinal_answer('never executed')",
        "final_answer('finish the actual saved change')",
    ])
    assert rc == 0, result
    writes = [e for e in events if e['event'] == 'file_write' and e.get('changed')]
    assert len(writes) == 1
    assert any(e['event'] == 'agent_error' for e in events)
    assert [e['rc'] for e in events if e['event'] == 'command_result'] == [1, 0]
    assert sum(bool(step.get('is_final_answer')) for step in memory) == 1
    assert writes[0]['file_hash'] in json.dumps(calls[1])


def test_official_final_check_rejects_passed_test_from_previous_version(tmp_path):
    stale = "run_command(argv=['python','-m','pytest','-q'])\nr=read_file(path='calc.py')\nwrite_file(path='calc.py', content='answer = 41\\n', expected_hash=r['file_hash'])\nfinal_answer('old test passed')"
    repair = "r=read_file(path='calc.py')\nwrite_file(path='calc.py', content='answer = 42\\n', expected_hash=r['file_hash'])\nfinal_answer('current version passes')"
    rc, result, calls, events, memory = run_final_check(tmp_path, [start(42), stale, repair])
    assert rc == 0, result
    assert len(calls) == 3
    assert [e['rc'] for e in events if e['event'] == 'command_result'] == [1, 0, 1, 0]
    assert any(e['event'] == 'agent_error' and 'Verification failed' in e['error'] for e in events)
    assert sum(bool(step.get('is_final_answer')) for step in memory) == 1
