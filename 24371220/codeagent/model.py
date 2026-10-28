"""One audited, budgeted path for all model traffic."""
import json
import os
import time
import urllib.error
import urllib.request


def body_size(body):
    return len(json.dumps(body, ensure_ascii=False, separators=(",", ":")))


def effective_body(body, efficiency=False):
    projected = dict(body)
    if efficiency:
        projected.update(temperature=0, top_p=1, max_tokens=4096,
                         presence_penalty=0, frequency_penalty=0, n=1)
        projected.update({"enable_thinking": False} if str(body["model"]).startswith("qwen")
                         else {"thinking": {"type": "disabled"}})
    return projected


class ModelClient:
    def __init__(self, config, log, max_calls=20, hard_limit=32000,
                 action_mode="code", efficiency=False, deadline=None, transport=None):
        self.config, self.log = config, log
        self.max_calls, self.hard_limit = max_calls, hard_limit
        self.action_mode, self.efficiency = action_mode, efficiency
        self.deadline, self.transport = deadline, transport
        self.calls = 0
        self.usage = {"complete": True, "requests": 0, "input_tokens": 0,
                      "output_tokens": 0, "total_tokens": 0}

    def prepare(self, messages):
        body = {"model": self.config["model"], "messages": messages, "stream": False,
                "temperature": self.config.get("temperature", 0),
                "max_tokens": self.config.get("max_tokens", 4096)}
        if self.action_mode == "json":
            body["response_format"] = {"type": "json_object"}
        # Apply only explicit, portable caller options; never copy credentials into bodies.
        for key in ("top_p", "thinking", "enable_thinking", "presence_penalty", "frequency_penalty", "n"):
            if key in self.config:
                body[key] = self.config[key]
        return body

    def budget_body(self, messages):
        return effective_body(self.prepare(messages), self.efficiency)

    def send(self, body):
        if self.calls >= self.max_calls:
            raise RuntimeError("MODEL_BUDGET_EXHAUSTED")
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise RuntimeError("RUN_TIMEOUT")
        if body_size(effective_body(body, self.efficiency)) > self.hard_limit:
            self.log("request_rejected", reason="CONTEXT_BUDGET_EXCEEDED", chars=body_size(body))
            raise ValueError("CONTEXT_BUDGET_EXCEEDED")
        self.calls += 1
        request_id = f"request-{self.calls:04d}"
        self.log("model_request", request_id=request_id, body=body)
        try:
            if self.transport is not None:
                response = self.transport(body)
            else:
                secret = os.environ.get(self.config["key_env"], "")
                if not secret:
                    raise ValueError("Missing configured API key environment variable")
                request = urllib.request.Request(
                    self.config["base_url"].rstrip("/") + "/chat/completions",
                    json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                    {"Content-Type": "application/json", "Authorization": "Bearer " + secret})
                timeout = float(self.config.get("request_timeout", 90))
                if self.deadline is not None:
                    timeout = min(timeout, max(.1, self.deadline - time.monotonic()))
                with urllib.request.urlopen(request, timeout=timeout) as stream:
                    response = json.load(stream)
        except Exception as exc:
            detail = exc.read().decode("utf-8", "replace") if isinstance(exc, urllib.error.HTTPError) else str(exc)
            self.usage["complete"] = False
            self.log("model_error", request_id=request_id, error=detail)
            raise RuntimeError("MODEL_REQUEST_FAILED: " + detail) from exc
        # Preserve raw API response before validation, including missing or invalid usage.
        self.log("model_response", request_id=request_id, response=response)
        usage = response.get("usage", {}) if isinstance(response, dict) else {}
        self.log("usage", request_id=request_id,
                 actual_model=response.get("model") if isinstance(response, dict) else None, usage=usage)
        values = [usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")] if isinstance(usage, dict) else [None] * 3
        valid = all(type(v) is int and v >= 0 for v in values)
        if not valid or values[0] + values[1] != values[2] or values[2] == 0:
            self.usage["complete"] = False
            raise RuntimeError("USAGE_INCOMPLETE: no comparable token total")
        self.usage["requests"] += 1
        for key, value in zip(("input_tokens", "output_tokens", "total_tokens"), values):
            self.usage[key] += value
        try:
            content = response["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("text response required")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise RuntimeError("MODEL_RESPONSE_INVALID") from exc
        return {"request_id": request_id, "response": response, "content": content}

    def summary(self):
        result = dict(self.usage, attempted_requests=self.calls)
        if not result["complete"]:
            for name in ("input_tokens", "output_tokens", "total_tokens"):
                result[name] = None
        return result
