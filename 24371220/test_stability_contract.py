import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from course_agent.workspace import WorkspaceTools
from course_agent.evidence import EvidenceStore, PAPER_QUESTIONS


def test_batch_atomic_and_versions(tmp_path):
    path = tmp_path / 'x.py'
    path.write_text('alpha beta gamma', encoding='utf-8')
    logs = []
    ws = WorkspaceTools(tmp_path, tmp_path, {'x.py'}, lambda *a, **k: logs.append((a, k)))
    h = ws.current_hash('x.py')
    def run(edits, version=h):
        return ws.invoke('replace_text_batch', {'path': 'x.py', 'edits': edits, 'expected_hash': version})
    with pytest.raises(ValueError):
        run([{'old_text': 'alpha', 'new_text': 'A'}, {'old_text': 'missing', 'new_text': 'B'}])
    with pytest.raises(ValueError):
        run([{'old_text': 'alpha beta', 'new_text': 'A'}, {'old_text': 'beta', 'new_text': 'B'}])
    assert path.read_text() == 'alpha beta gamma'
    result = run([{'old_text': 'alpha', 'new_text': 'A'}, {'old_text': 'gamma', 'new_text': 'G'}])
    assert result['changed'] and result['before_hash'] == h and path.read_text() == 'A beta G'
    with pytest.raises(ValueError): run([{'old_text': 'A', 'new_text': 'Z'}])
    assert any(a[0] == 'file_write' and k['content'] == 'A beta G' for a, k in logs)


def test_paper_saved_answer_validation_and_serialization(tmp_path):
    (tmp_path / 'paper.pdf').write_text('version', encoding='utf-8')
    ws = WorkspaceTools(tmp_path, tmp_path, set(), lambda *a, **k: None)
    contract = SimpleNamespace(profile='paper', topics=tuple(PAPER_QUESTIONS), paper_pages=tuple(range(1, 53)))
    store = EvidenceStore(contract, ws, lambda *a, **k: None)
    quote = 'A continuous "quotation" with a newline\nand a backslash \\ plus 中文.'
    eid = store._add('paper.pdf', ws.current_hash('paper.pdf'), 'page:1', quote, page=1)
    store.exposed.add(eid)
    for bad in (None, True, 100):
        with pytest.raises(ValueError): store.save_answer('overview', 'categories', bad, eid, 1, quote)
    with pytest.raises(ValueError): store.save_answer('overview', 'categories', ['a'], eid, True, quote)
    with pytest.raises(ValueError): store.save_answer('overview', 'categories', ['a'], eid, 2, quote)
    with pytest.raises(ValueError): store.save_answer('overview', 'categories', ['a'], eid, 1, 'not found quotation at all')
    for invalid_quote in (None, 12, True):
        with pytest.raises(ValueError): store.save_answer('overview', 'categories', ['a'], eid, 1, invalid_quote)
    supplied = ['a']
    store.save_answer('overview', 'categories', supplied, eid, 1, quote)
    supplied.append(None)
    assert store.answers['overview']['categories']['answer'] == ['a']
    for section, questions in PAPER_QUESTIONS.items():
        store.save_section(section, 'summary', 'application')
        for question, kind in questions.items():
            answer = ['a'] if kind is list else 123 if kind is int else 'answer'
            store.save_answer(section, question, answer, eid, 1, quote)
    result = json.loads(json.dumps(store.report('overview')))
    assert result['sections'][2]['answers']['toolbench_api_count'] == 123
    assert result['sections'][0]['evidence'][0]['quote'] == quote
    (tmp_path / 'paper.pdf').write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError): store.report('overview')


@pytest.mark.parametrize('first_edit', ['good', 'bad'])
def test_official_final_runs_verification_and_recovers(tmp_path, monkeypatch, first_edit):
    from test_smolagents import run_script
    monkeypatch.setattr(EvidenceStore, 'missing', lambda self, first_write=True: [])
    def setup(repo):
        (repo / 'data.py').write_text('value = 0\n')
        (repo / 'test_data.py').write_text("from pathlib import Path\ndef test_value():\n    assert Path('data.py').read_text() == 'value = 1\\n'\n")
    replies = [
        "update_plan(items=[{'title':'change','status':'doing'}])\nrun_command(argv=['python','-m','pytest','-q'])\nr=read_file(path='data.py')",
        "r=replace_text_batch(path='data.py', edits=[{'old_text':'value = 0','new_text':'value = " + ('1' if first_edit == 'good' else '2') + "'}], expected_hash=r['file_hash'])\nfinal_answer('done')",
    ]
    if first_edit == 'bad':
        replies.append("r=read_file(path='data.py')\nr=replace_text_batch(path='data.py', edits=[{'old_text':'value = 2','new_text':'value = 1'}], expected_hash=r['file_hash'])\nfinal_answer('done')")
    rc, result, calls, events = run_script(tmp_path, replies, config={'editable':['data.py'], 'read_only':False, 'max_steps':len(replies)}, profile='source', setup=setup)
    assert rc == 0, result
    assert len(calls) == len(replies)
    assert any(e['event'] == 'agent_step' and e['step'].get('is_final_answer') for e in events)
    if first_edit == 'bad': assert any(e['event'] == 'agent_error' for e in events)
