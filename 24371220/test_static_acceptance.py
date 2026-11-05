"""Run existing course gates and capacity regressions with static compaction on."""
import json
import pytest

from test_smolagents import CONFIG
from test_smolagents_materials import (
    MATERIALS,
    build_session,
    test_real_pdf_52_pages_fit_batched_and_five_notes_reused,
    test_real_three_file_preedit_coverage_and_source_notes,
    test_large_source_cannot_evict_latest_error,
)
from test_paper_delivery import (
    paper_runtime,
    test_final_note_revision_requires_new_http_before_report_and_finish,
    test_failed_http_batch_recovers_then_success_advances,
)
from test_stability_review import (
    test_official_final_check_runs_current_verification_and_records_success,
    test_official_final_check_failure_recovers_after_model_repairs,
    test_official_final_check_rejects_passed_test_from_previous_version,
    test_successful_write_survives_later_statement_error,
)


@pytest.fixture(autouse=True)
def enable_static_compaction(monkeypatch):
    monkeypatch.setitem(CONFIG, 'static_context_compact', True)


@pytest.mark.parametrize('profile,task_number', [('source', '题目2'), ('paper', '题目1')])
def test_real_task_initial_request_savings(tmp_path, build_session, monkeypatch, profile, task_number):
    task = (MATERIALS / '公开任务' / task_number / 'task.md').read_text(encoding='utf-8')
    measurements = []
    for compact in (False, True):
        monkeypatch.setitem(CONFIG, 'static_context_compact', compact)
        repo = tmp_path / str(compact)
        repo.mkdir()
        if profile == 'paper':
            (repo / 'paper.json').write_text('{"required_pages":[1,52]}')
            (repo / 'report.json').write_text('{}')
        session, context, agent, model = build_session(profile, repo, task)
        view = context.build(agent.memory, model)
        assert session.task_prompt().startswith(task + '\n\n')
        measurements.append({'compact': compact, 'system_text': len(agent.system_prompt),
                             'task_text': len(session.task_prompt()), **model.measure(view)})
    assert measurements[1]['chars'] < measurements[0]['chars'] <= 32000
    (tmp_path / 'capacity.json').write_text(json.dumps({'profile': profile, 'measurements': measurements}, indent=2))
