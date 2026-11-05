"""Offline metering regressions against actual HTTP requests; no provider calls."""
import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from course_agent.audit import (CONTEXT_CATEGORIES, AuditedOpenAIModel, RequestAudit,
                                compact, context_accounting)
from course_agent.context import message
from smolagents.models import MessageRole
from test_smolagents import CONFIG, response, run_script


def reconciles(accounting, body):
    assert set(accounting['text_json_chars']) == set(CONTEXT_CATEGORIES)
    assert accounting['compact_json_chars'] == len(compact(body))
    assert accounting['json_wrapper_chars'] >= 0
    assert sum(accounting['text_json_chars'].values()) + accounting['json_wrapper_chars'] == len(compact(body))


@pytest.mark.parametrize('role', ['user', 'assistant', 'tool'])
def test_text_contributions_escape_once_and_wrapper_includes_roles(role):
    text = '中文 "quoted"\\path\n\t\x01'
    body = {'messages': [{'role': role, 'name': 'metadata', 'content': [
        {'type': 'text', 'text': text},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,abcd'}}]}],
        'model': 'offline', 'response_format': {'type': 'json_object'}}
    before = copy.deepcopy(body)
    result = context_accounting(body, [('evidence', text)])
    assert body == before
    assert result['text_chars']['evidence'] == len(text)
    assert result['text_json_chars']['evidence'] == len(compact(text)) - 2
    assert sum(result['text_chars'].values()) == len(text)
    assert result['unmatched_manifest_segments'] == 0
    reconciles(result, body)


def test_unknown_message_and_unmatched_manifest_fall_back_without_guessing():
    body = {'messages': [{'role': 'user', 'content': 'Evidence: an unknown message'},
                         {'role': 'assistant', 'content': None}]}
    result = context_accounting(body, [('evidence', 'a missing complete evidence segment')])
    assert result['text_chars']['other'] == len(body['messages'][0]['content'])
    assert result['text_chars']['evidence'] == 0
    assert result['unmatched_manifest_segments'] == 1
    reconciles(result, body)


def test_actual_sdk_body_identical_with_meter_disabled_and_all_groups_accounted():
    captured, all_events = [], []
    segments = [(kind, f'{kind}: 中文 "quote"\\value\n')
                for kind in CONTEXT_CATEGORIES if kind not in {'core', 'tool'}]
    messages = [message('Core rules.\nAvailable tools:\nprint(value)', MessageRole.SYSTEM)]
    messages.extend(message(text) for _, text in segments)
    for enabled in (True, False):
        events = []
        audit = RequestAudit(SimpleNamespace(max_calls=3, timeout=60, hard_chars=100000,
                                             content_chars=None),
                             lambda event, **fields: events.append({'event': event, **fields}),
                             context_accounting=enabled)
        audit.context_segments = segments

        def handler(request):
            captured.append(bytes(request.content))
            return httpx.Response(200, json=response('ok'))

        model = AuditedOpenAIModel(CONFIG, audit, 'offline', transport=httpx.MockTransport(handler))
        try:
            model.generate(messages)
        finally:
            model.close()
        assert audit.calls == 1
        all_events.append(events)
    assert captured[0] == captured[1]
    meters = [event for event in all_events[0] if event['event'] == 'context_accounting']
    assert len(meters) == 1
    assert not any(event['event'] == 'context_accounting' for event in all_events[1])
    result = meters[0]
    body = json.loads(captured[0])
    assert all(result['text_chars'][kind] > 0 for kind in CONTEXT_CATEGORIES)
    assert result['unmatched_manifest_segments'] == 0
    assert result['wire_bytes'] == len(captured[0])
    assert result['wire_chars'] == len(captured[0].decode('utf-8'))
    reconciles(result, body)


def test_context_sidecar_preserves_multi_request_body_and_evidence_selection(tmp_path, monkeypatch):
    original_init = RequestAudit.__init__
    runs = []
    for enabled in (True, False):
        def init(self, *args, **kwargs):
            original_init(self, *args, **kwargs, context_accounting=enabled)
        monkeypatch.setattr(RequestAudit, '__init__', init)
        root = tmp_path / str(enabled)
        root.mkdir()
        result = run_script(root, [
            "update_plan(items=[{'title':'read and finish','status':'doing'}])\nprint(read_file(path='data.txt'))",
            "update_plan(items=[{'title':'read and finish','status':'done'}])\nfinal_answer('done')",
        ], setup=lambda repo: (repo / 'data.txt').write_text('source line\n' * 20))
        assert result[0] == 0, result[1]
        runs.append(result)
    assert runs[0][2] == runs[1][2]
    selections = [[{key: value for key, value in event.items()
                    if key not in {'time', 'run_id', 'seq'}}
                   for event in run[3] if event['event'] == 'context_selection'] for run in runs]
    assert selections[0] == selections[1]
    meters = [event for event in runs[0][3] if event['event'] == 'context_accounting']
    assert len(meters) == len(runs[0][2]) == 2
    for meter, body in zip(meters, runs[0][2]):
        reconciles(meter, body)
        assert meter['text_chars']['task'] > 0
        assert meter['text_chars']['status'] > 0
        assert meter['unmatched_manifest_segments'] == 0
    assert all(meters[-1]['text_chars'][kind] > 0 for kind in ('plan', 'recent', 'evidence'))
    assert not any(event['event'] == 'context_accounting' for event in runs[1][3])
