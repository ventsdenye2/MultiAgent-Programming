"""Audit the actual SDK HTTP body; no second model transport or retry loop."""
import json
import os
import time

import httpx
from smolagents import OpenAIModel


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def request_size(body):
    """Measure the wire body and the basic evaluator's content serialization."""
    messages = body.get('messages', [])
    return {
        'chars': len(compact(body)),
        # Preserve the original diagnostic field; the course meter below is
        # intentionally different for structured multimodal/text content.
        'content_chars': sum(len(t) for m in messages for t in strings(m.get('content', ''))),
        'course_content_chars': sum(len(m.get('content', '')) if isinstance(m.get('content'), str)
                                    else len(json.dumps(m.get('content'), ensure_ascii=False))
                                    for m in messages),
    }


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def contains(value, text):
    forms = (text, json.dumps(text, ensure_ascii=False)[1:-1], json.dumps(text)[1:-1])
    return any(form in item for item in strings(value) for form in forms)


class BudgetExceeded(RuntimeError):
    pass


def reserve_request(path):
    """A native-run budget shared by all sequential task subprocesses."""
    import fcntl
    with open(path, 'r+', encoding='utf-8') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        data = json.load(stream)
        limit, used = data.get('limit'), data.get('used')
        if type(limit) is not int or type(used) is not int or limit < 1 or used < 0:
            raise BudgetExceeded('RUN_REQUEST_BUDGET_INVALID')
        if used >= limit:
            raise BudgetExceeded('RUN_REQUEST_BUDGET')
        data['used'] += 1
        stream.seek(0)
        json.dump(data, stream)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())
        return data


class RequestAudit:
    def __init__(self, contract, log, evidence=None):
        self.contract, self.log, self.evidence = contract, log, evidence
        self.started = time.monotonic()
        self.calls = 0
        self.completed = set()
        self.bodies = []
        self.usage = []
        self.last_response = None
        self.stop_reason = None
        self.last_classification = None
        self.request_budget_path = os.environ.get('CODE_AGENT_REQUEST_BUDGET_FILE')

    def guard(self):
        if self.calls >= self.contract.max_calls:
            self.stop_reason = "MODEL_CALL_BUDGET"
        elif time.monotonic() - self.started >= self.contract.timeout:
            self.stop_reason = "RUN_TIMEOUT"
        if self.stop_reason:
            raise BudgetExceeded(self.stop_reason)

    def request(self, request):
        self.guard()
        body = json.loads(request.content)
        size = request_size(body)
        if size['chars'] > self.contract.hard_chars or (
            self.contract.content_chars and size['course_content_chars'] > self.contract.content_chars
        ):
            self.stop_reason = "REQUEST_CHAR_BUDGET"
            self.log("request_blocked", **size)
            raise BudgetExceeded(self.stop_reason)
        if self.request_budget_path:
            try:
                reservation = reserve_request(self.request_budget_path)
            except (BudgetExceeded, OSError, ValueError) as exc:
                self.stop_reason = str(exc) if isinstance(exc, BudgetExceeded) else 'RUN_REQUEST_BUDGET_INVALID'
                raise BudgetExceeded(self.stop_reason) from exc
            self.log('request_budget', **reservation)
        self.calls += 1
        self.bodies.append(body)
        self.log("model_request", number=self.calls, body=body, **size)

    def response(self, response):
        response.read()
        try:
            payload = response.json()
        except ValueError:
            self.error("INVALID_JSON_RESPONSE")
            return
        if response.is_error:
            self.error("HTTP_" + str(response.status_code), response=payload)
            return
        self.completed.add(self.calls)
        self.last_response = payload
        choices = payload.get("choices") or [{}]
        choice = choices[0]
        content = (choice.get("message") or {}).get("content") or ""
        reason = choice.get("finish_reason")
        category = ("truncated_empty" if not content else "truncated") if reason == "length" else (
            "empty" if not content else "ok")
        self.last_classification = category
        usage = payload.get("usage") or {}
        complete = (all(type(usage.get(k)) is int and usage[k] >= 0
                        for k in ("prompt_tokens", "completion_tokens", "total_tokens"))
                    and usage.get('total_tokens') == usage.get('prompt_tokens', 0) + usage.get('completion_tokens', 0))
        self.usage.append({"complete": complete, **usage})
        self.log("model_response", number=self.calls, response=payload, classification=category)
        if complete:
            self.log('usage', usage=usage, actual_model=payload.get('model'), number=self.calls)
        if content and self.evidence:
            self.evidence.mark_exposed(self.bodies[-1], payload, self.calls)

    def error(self, category, **fields):
        if self.calls and self.calls not in self.completed:
            self.completed.add(self.calls)
            self.usage.append({"complete": False})
            self.log("model_error", number=self.calls, classification=category, **fields)

    def totals(self):
        return {"requests": self.calls, "complete": len(self.usage) == self.calls and
                all(x["complete"] for x in self.usage),
                "prompt_tokens": sum(x.get("prompt_tokens", 0) for x in self.usage),
                "completion_tokens": sum(x.get("completion_tokens", 0) for x in self.usage)}


class AuditedOpenAIModel(OpenAIModel):
    """Official SDK transport with auditing and DeepSeek response-format support."""
    def __init__(self, config, audit, api_key, transport=None):
        self.audit = audit
        self.action_stop_sequences = ['Observation:', 'Calling tools:']
        self.action_response_format = None
        client = httpx.Client(timeout=httpx.Timeout(float(config.get("timeout", 210))),
                              transport=transport,
                              event_hooks={"request": [audit.request], "response": [audit.response]})
        super().__init__(model_id=config["model"], api_base=config["base_url"], api_key=api_key,
                         retry=False, client_kwargs={"max_retries": 0, "http_client": client},
                         max_tokens=4096, extra_body={"thinking": {"type": "disabled"}})

    def _prepare_completion_kwargs(self, *args, **kwargs):
        body = super()._prepare_completion_kwargs(*args, **kwargs)
        # DeepSeek Chat Completions supports JSON mode, not json_schema. Keep
        # CodeAgent's official thought/code prompt and parser; adapt only the
        # provider parameter, without rewriting or repairing model responses.
        if (body.get('response_format') or {}).get('type') == 'json_schema':
            body['response_format'] = {'type': 'json_object'}
        return body

    def generate(self, messages, **kwargs):
        self.audit.guard()
        try:
            return super().generate(messages, **kwargs)
        except Exception as exc:
            self.audit.error("NETWORK_OR_RESPONSE_ERROR", error_type=type(exc).__name__)
            raise

    def measure(self, messages):
        body = self._prepare_completion_kwargs(messages, model=self.model_id,
                                              stop_sequences=self.action_stop_sequences,
                                              response_format=self.action_response_format,
                                              custom_role_conversions=self.custom_role_conversions,
                                              convert_images_to_image_urls=True)
        body.update(body.pop("extra_body", {}))
        return request_size(body)

    def estimate(self, messages):
        return self.measure(messages)['chars']

    def close(self):
        self.client.close()
