"""Offline ModelClient request, budget, and token-usage checks."""
import pytest
import io
import json

from codeagent.model import ModelClient, body_size, effective_body


@pytest.mark.parametrize('remaining,expected', [(None, 210), (12, 12)])
@pytest.mark.parametrize('fail', [False, True])
def test_http_timeout_and_accounting(monkeypatch, remaining, expected, fail):
    events, calls = [], []
    clock = [100.0]
    monkeypatch.setenv('TEST_KEY', 'fake-offline')
    monkeypatch.setattr('codeagent.model.time.monotonic', lambda: clock[0])
    def open_request(request, timeout):
        calls.append(timeout)
        clock[0] += 2
        if fail:
            raise TimeoutError('simulated timeout')
        return io.BytesIO(json.dumps(good_response()).encode())
    monkeypatch.setattr('codeagent.model.urllib.request.urlopen', open_request)
    client = ModelClient({'model':'fake', 'base_url':'http://offline.invalid', 'key_env':'TEST_KEY'},
                         lambda e, **k: events.append((e,k)),
                         deadline=None if remaining is None else 100 + remaining)
    body = client.prepare([{'role':'user','content':'test'}])
    if fail:
        with pytest.raises(RuntimeError, match='MODEL_REQUEST_FAILED'):
            client.send(body)
        assert client.summary()['input_tokens'] is None
        end = next(k for e,k in events if e == 'model_error')
        assert end['usage_confirmed'] is False
    else:
        client.send(body)
        end = next(k for e,k in events if e == 'model_response')
    assert calls == [expected] and client.calls == 1
    assert end['elapsed_seconds'] == 2 and end['timeout_seconds'] == expected
    assert end['remaining_seconds'] == (None if remaining is None else remaining-2)


def good_response(content="ok", prompt=7, completion=3):
    return {"model": "fake", "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                      "total_tokens": prompt + completion}}


def test_request_hard_budget_counts_full_body_and_efficiency_proxy_parameters():
    events=[];sent=[]
    transport=lambda body:(sent.append(body) or good_response())
    client=ModelClient({"model":"fake","temperature":0.4,"max_tokens":10},
                       lambda event,**kw:events.append((event,kw)),max_calls=3,
                       hard_limit=10000,action_mode="json",efficiency=True,transport=transport)
    messages=[{"role":"system","content":"固定指令"},{"role":"user","content":"任务"}]
    body=client.prepare(messages)
    projected=effective_body(body,True)
    # The hard check includes JSON mode and all efficiency proxy fields, not just messages.
    client.hard_limit=body_size(projected)
    result=client.send(body)
    assert result["content"]=="ok" and sent==[body]
    assert projected["response_format"]=={"type":"json_object"}
    assert projected["temperature"]==0 and projected["top_p"]==1
    assert projected["max_tokens"]==4096 and projected["presence_penalty"]==0
    assert projected["frequency_penalty"]==0 and projected["n"]==1
    assert projected["thinking"]=={"type":"disabled"}
    client.hard_limit=body_size(projected)-1
    with pytest.raises(ValueError,match="CONTEXT_BUDGET_EXCEEDED"):
        client.send(body)
    assert len(sent)==1
    rejected=[fields for event,fields in events if event=="request_rejected"]
    assert rejected and rejected[-1]["reason"]=="CONTEXT_BUDGET_EXCEEDED"


@pytest.mark.parametrize("usage", [
    None,
    {},
    {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 0},
    {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 4},
    {"prompt_tokens": "1", "completion_tokens": 2, "total_tokens": 3},
    {"prompt_tokens": -1, "completion_tokens": 2, "total_tokens": 1},
])
def test_missing_or_invalid_usage_never_becomes_zero_and_is_not_retried(usage):
    events=[];calls=[]
    response={"model":"fake","choices":[{"message":{"content":"must not execute"}}]}
    if usage is not None:response["usage"]=usage
    client=ModelClient({"model":"fake"},lambda e,**k:events.append((e,k)),max_calls=4,
                       hard_limit=5000,transport=lambda body:(calls.append(body) or response))
    with pytest.raises(RuntimeError,match="USAGE_INCOMPLETE"):
        client.send(client.prepare([{"role":"user","content":"go"}]))
    summary=client.summary()
    assert calls and len(calls)==1
    assert summary["attempted_requests"]==1 and summary["requests"]==0
    assert summary["complete"] is False
    assert summary["input_tokens"] is None and summary["output_tokens"] is None and summary["total_tokens"] is None
    assert [e for e,_ in events].count("model_request")==1
    assert [e for e,_ in events].count("model_response")==1
    assert [e for e,_ in events].count("usage")==1


def test_model_call_budget_blocks_transport_after_configured_limit():
    calls=[];events=[]
    client=ModelClient({"model":"fake"},lambda e,**k:events.append(e),max_calls=1,
                       hard_limit=5000,transport=lambda body:(calls.append(body) or good_response()))
    body=client.prepare([{"role":"user","content":"one"}])
    client.send(body)
    with pytest.raises(RuntimeError,match="MODEL_BUDGET_EXHAUSTED"):
        client.send(body)
    assert len(calls)==1 and client.calls==1
    assert events.count("model_request")==1


def test_network_failure_is_logged_once_and_marks_usage_incomplete():
    events=[];attempts=[]
    def fail(body):
        attempts.append(body)
        raise ConnectionError("offline transport failed")
    client=ModelClient({"model":"fake"},lambda e,**k:events.append((e,k)),max_calls=3,
                       hard_limit=5000,transport=fail)
    body=client.prepare([{"role":"user","content":"offline"}])
    with pytest.raises(RuntimeError,match="MODEL_REQUEST_FAILED: offline transport failed"):
        client.send(body)
    summary=client.summary()
    assert len(attempts)==1 and client.calls==1
    assert summary["complete"] is False and summary["attempted_requests"]==1
    assert summary["input_tokens"] is None and summary["output_tokens"] is None and summary["total_tokens"] is None
    assert [e for e,_ in events].count("model_request")==1
    errors=[fields for event,fields in events if event=="model_error"]
    assert len(errors)==1 and "offline transport failed" in errors[0]["error"]


def test_explicit_null_usage_is_incomplete_without_retry():
    attempts=[]
    response={"model":"fake","choices":[{"message":{"content":"must not execute"}}],"usage":None}
    client=ModelClient({"model":"fake"},lambda *_a,**_k:None,max_calls=2,hard_limit=5000,
                       transport=lambda body:(attempts.append(body) or response))
    with pytest.raises(RuntimeError,match="USAGE_INCOMPLETE"):
        client.send(client.prepare([{"role":"user","content":"go"}]))
    assert len(attempts)==1
    summary=client.summary()
    assert summary["complete"] is False and summary["attempted_requests"]==1
    assert summary["input_tokens"] is None and summary["output_tokens"] is None and summary["total_tokens"] is None
