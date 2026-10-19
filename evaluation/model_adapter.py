"""Opt-in Chat Completions adapter; one request, no retries or model fallback.

No environment variables, credential files or discovery endpoints are read.
Injected transports are trusted application code, not a network sandbox.
Reservations bound approved exposure under an operator-supplied per-request
quote; they are NOT a provider-enforced monetary cap or verified invoice.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, asdict
from decimal import Decimal
import json
import math
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler


class ModelRequestError(RuntimeError):
    """Sanitized error. A dispatched request may have been billed."""


def _positive_money(value):
    if type(value) is not str:
        raise ValueError("money limits must be decimal strings")
    amount = Decimal(value)
    if not amount.is_finite() or amount <= 0:
        raise ValueError("finite positive money limit required")
    return amount


@dataclass(frozen=True)
class ModelConfig:
    endpoint: str
    model: str
    max_requests: int
    max_reserved_usd: str
    per_request_reserve_usd: str
    max_output_tokens: int = 2048
    max_request_bytes: int = 65536
    timeout_seconds: float = 60

    def __post_init__(self):
        p = urlsplit(self.endpoint)
        if (p.scheme != "https" or not p.hostname or p.username or p.password
                or p.query or p.fragment or p.port not in (None, 443)
                or not p.path.endswith("/chat/completions")):
            raise ValueError("explicit HTTPS Chat Completions endpoint required")
        if type(self.model) is not str or not self.model.strip() or len(self.model) > 128:
            raise ValueError("exact model ID required")
        for value, maximum in [(self.max_requests, 1000), (self.max_output_tokens, 8192),
                               (self.max_request_bytes, 1048576)]:
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("finite request/token/byte limits required")
        if (type(self.timeout_seconds) not in (int, float)
                or not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 180):
            raise ValueError("finite timeout required")
        if _positive_money(self.per_request_reserve_usd) > _positive_money(self.max_reserved_usd):
            raise ValueError("one request exceeds reservation limit")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ModelRequestError("redirect refused")


def https_json_transport(endpoint, payload, headers, timeout):
    """Called only by an explicitly approved client; no redirect forwarding."""
    request = Request(endpoint, data=json.dumps(payload, ensure_ascii=False,
                      allow_nan=False).encode("utf-8"), headers=headers, method="POST")
    try:
        with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            if response.geturl() != endpoint:
                raise ModelRequestError("redirect refused")
            raw = response.read(1048577)
            if len(raw) > 1048576:
                raise ModelRequestError("response too large")
            return json.loads(raw)
    except HTTPError as exc:
        exc.close()
        raise ModelRequestError("HTTP request failed; billing uncertain; no automatic retry") from None
    except Exception:
        raise ModelRequestError("request outcome uncertain; no automatic retry") from None


class ModelClient:
    def __init__(self, config, *, transport=None, api_key=None, allow_network=False):
        if type(config) is not ModelConfig:
            raise TypeError("ModelConfig required")
        if allow_network is not False and allow_network is not True:
            raise ValueError("explicit network boolean required")
        if transport is None:
            if not allow_network:
                raise ValueError("network disabled; explicit approval or offline transport required")
            if type(api_key) is not str or not api_key or any(c.isspace() for c in api_key):
                raise ValueError("transient credential required")
            transport = https_json_transport
        elif allow_network or api_key is not None:
            raise ValueError("offline injection cannot carry credentials or network approval")
        self.config, self.transport = config, transport
        self.execution_kind = "real_model_real_simulator" if allow_network else "mocked_smoke"
        self._api_key = api_key
        self.records = []
        self.frozen = False
        self.last_usage = None

    def close(self):
        self._api_key = None
        self.frozen = True

    def request(self, messages, *, tools=None, purpose="decision", json_output=False):
        self.last_usage = None
        c = self.config
        if self.frozen or len(self.records) >= c.max_requests:
            raise ModelRequestError("client stopped or request limit reached")
        reserved = _positive_money(c.per_request_reserve_usd) * (len(self.records) + 1)
        if reserved > _positive_money(c.max_reserved_usd):
            raise ModelRequestError("reservation limit reached before dispatch")
        payload = {"model": c.model, "messages": deepcopy(messages),
                   "max_tokens": c.max_output_tokens, "temperature": 0}
        if tools:
            payload.update(tools=deepcopy(tools), tool_choice="auto")
        if json_output:
            payload["response_format"] = {"type": "json_object"}
        if len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")) > c.max_request_bytes:
            raise ModelRequestError("input byte limit reached before dispatch")
        record = {"attempt": len(self.records) + 1, "purpose": purpose,
                  "status": "dispatched", "reserved_usd": c.per_request_reserve_usd,
                  "input_tokens": None, "output_tokens": None, "cost_usd": None,
                  "billing_verified": False, "execution_kind": self.execution_kind}
        self.records.append(record)
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = "Bearer " + self._api_key
        started = time.monotonic()
        try:
            response = self.transport(c.endpoint, payload, headers, c.timeout_seconds)
            encoded = json.dumps(response, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode("utf-8")) > 1048576 or (self._api_key and self._api_key in encoded):
                raise ValueError("unsafe response")
            if response.get("model") != c.model:
                raise ValueError("model mismatch")
            usage = response.get("usage") or {}
            for target, source in [("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens")]:
                v = usage.get(source)
                if type(v) is int and v >= 0:
                    record[target] = v
            if record['output_tokens'] is not None and record['output_tokens'] > c.max_output_tokens:
                raise ValueError('provider reported output beyond configured limit')
            message = response["choices"][0]["message"]
            if type(message) is not dict or message.get("role") != "assistant":
                raise ValueError("invalid assistant message")
            if response["choices"][0].get("finish_reason") not in {"stop", "tool_calls"}:
                raise ValueError("truncated or refused response")
            # Strip provider extras (e.g. private reasoning) before persistence.
            result = {k: deepcopy(message[k]) for k in ("role", "content", "tool_calls") if k in message}
            record["status"] = "received"
            return result
        except Exception:
            self.frozen = True
            record["status"] = "outcome_unknown"
            raise ModelRequestError("model request failed; outcome/billing uncertain; no retry") from None
        finally:
            record["latency_seconds"] = time.monotonic() - started
            self.last_usage = deepcopy(record)

    def complete(self, messages, tools):
        return self.request(messages, tools=tools)

    def public_config(self):
        return {**asdict(self.config), "execution_kind": self.execution_kind,
                "billing_verified": False, "provider_enforced_monetary_cap": False}
