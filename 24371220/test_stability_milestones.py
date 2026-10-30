import json

from analyze_stability import milestones


def test_only_executed_events_count_after_partial_action_failure(tmp_path):
    events = [
        {'event': 'model_request', 'number': 1},
        {'event': 'command_result', 'argv': ['/python', '-m', 'pytest', '-q'], 'rc': 1},
        {'event': 'model_request', 'number': 2},
        {'event': 'file_write', 'path': 'report.json', 'changed': True, 'file_hash': 'v2'},
        {'event': 'agent_error', 'error_type': 'AgentExecutionError', 'error': 'import os'},
        {'event': 'model_request', 'number': 3},
        {'event': 'command_result', 'argv': ['/python', '-m', 'pytest', '-q'], 'rc': 0},
        {'event': 'agent_step', 'step': {'is_final_answer': True}},
    ]
    path = tmp_path / 'run.log'
    path.write_text('\n'.join(json.dumps(dict(e, seq=i)) for i, e in enumerate(events)), encoding='utf-8')
    result = milestones(path)
    assert result['first_write']['request'] == 2
    assert [t['request'] for t in result['tests_after_last_write']] == [3]
    assert result['finish'][0]['request'] == 3
    assert result['protocol_errors'] == result['tool_errors'] == result['infrastructure_errors'] == 0
    assert len(result['errors']) == 1
