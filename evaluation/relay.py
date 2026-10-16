"""Finite, no-auto-retry OpenAI-compatible relay adapter.

API key must be supplied transiently by a supported secret channel. No CLI/env
loader or credential persistence is provided. No endpoint is claimed verified by
this module. Exact host/model restrictions implement the user's bounded scope.
Model list/response IDs are relay claims, not proof of backend model identity.
No monetary billing estimate is fabricated from token counts.
"""
from __future__ import annotations
import json
import math
import socket
import sys
from project_paths import upstream_path
sys.path.insert(0, str(upstream_path() / "src"))
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

ALLOWED_HOST = 'st.walkcoding.top'
EXACT_MODEL = 'gpt-6.1-sol'


class RelayError(RuntimeError):
    pass

class RelayOutcomeUncertain(RelayError):
    """Request may have been billed; never retry this automatically."""

class RedirectRejected(RelayError):
    pass

class RelayHTTPError(RelayError):
    def __init__(self, status):
        self.status = int(status)
        super().__init__(f'HTTP {self.status}; no automatic retry; billing status unknown')

class ExactModelUnavailable(RelayError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RedirectRejected('redirect rejected before credential forwarding')


def _validate_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != ALLOWED_HOST or
        parsed.port not in (None, 443) or parsed.username or parsed.password or
        parsed.query or parsed.fragment or parsed.path not in
        {'/v1/models', '/v1/chat/completions', '/v1/responses'}):
        raise ValueError('relay URL outside explicitly approved HTTPS host/path scope')


def https_transport(url, method, payload, headers, timeout):
    """No redirect following, one physical request, sanitized exceptions only."""
    _validate_url(url)
    body = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    request = Request(url, data=body, method=method, headers=headers)
    opener = build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.geturl() != url:
                raise RedirectRejected('unexpected response URL')
            raw = response.read(10 * 1024 * 1024 + 1)
            if len(raw) > 10 * 1024 * 1024:
                raise RelayOutcomeUncertain('response exceeded size bound; no retry')
            try:
                decoded = json.loads(raw)
            except (UnicodeError, json.JSONDecodeError):
                raise RelayOutcomeUncertain('invalid JSON response; billing unknown; no retry') from None
            return decoded
    except RedirectRejected:
        raise
    except HTTPError as exc:
        # Error bodies/headers may reflect secrets. Never read, log or propagate.
        status = exc.code
        exc.close()
        raise RelayHTTPError(status) from None
    except (URLError, TimeoutError, socket.timeout, OSError):
        raise RelayOutcomeUncertain('transport failed; outcome/billing uncertain; no automatic retry') from None


class AttemptAccounting:
    """Serial, shared experiment cap covering discovery, smoke and every retry.

    This request-count contract is not a monetary cap. Cost remains unknown unless verified
    separately. This interface does not call any provider or retry by itself.
    """
    def __init__(self, max_attempts, max_wall_seconds=7200):
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError('finite positive physical-attempt limit required')
        if not isinstance(max_wall_seconds, (int, float)) or not math.isfinite(max_wall_seconds) or max_wall_seconds <= 0:
            raise ValueError('finite wall-clock budget required')
        self.max_attempts = max_attempts
        self.max_wall_seconds = max_wall_seconds
        self.started = time.monotonic()
        self.frozen = False
        self.records = []
    def reserve(self, purpose):
        if self.frozen or time.monotonic() - self.started >= self.max_wall_seconds:
            raise RelayError('experiment stopped or wall-clock budget exhausted')
        if len(self.records) >= self.max_attempts:
            raise RelayError('physical-attempt budget exhausted')
        record = {'attempt': len(self.records) + 1, 'purpose': purpose,
                  'status': 'reserved', 'input_tokens': None, 'output_tokens': None,
                  'cost_usd': None, 'billing_verified': False}
        self.records.append(record)
        return record


class RelayClient:
    execution_kind = 'real_model_real_simulator'

    def __init__(self, *, api_key, endpoint, accounting, transport=https_transport,
                 max_output_tokens=512, timeout=90):
        _validate_url(endpoint)
        if urlsplit(endpoint).path not in {'/v1/chat/completions', '/v1/responses'}:
            raise ValueError('generation endpoint required')
        if not isinstance(api_key, str) or not api_key or any(c.isspace() for c in api_key):
            raise ValueError('transient API key required')
        if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 4096:
            raise ValueError('finite output-token bound required')
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 180:
            raise ValueError('finite request timeout required')
        self._api_key = api_key
        self.endpoint, self.accounting, self.transport = endpoint, accounting, transport
        self.max_output_tokens, self.timeout = max_output_tokens, timeout
        self.last_usage = None
        self.model_evidence = []
        self.model_available = False

    def close(self):
        self._api_key = None

    def _call(self, url, method, payload, purpose):
        if not self._api_key:
            raise RelayError('transient credential unavailable or cleared')
        record = self.accounting.reserve(purpose)
        started = time.monotonic()
        try:
            response = self.transport(url, method, payload,
                {'Authorization': 'Bearer ' + self._api_key, 'Content-Type': 'application/json'}, self.timeout)
            if not isinstance(response, dict):
                raise RelayOutcomeUncertain('invalid response shape; no retry')
            # Protect artifacts against a relay reflecting the credential.
            encoded = json.dumps(response, ensure_ascii=False, allow_nan=False)
            if self._api_key in encoded:
                raise RelayOutcomeUncertain('response reflected credential; response discarded')
            record['status'] = 'response_received'
            return response, record
        except Exception as exc:
            record['status'] = 'outcome_unknown'
            self.accounting.frozen = True
            record['error_type'] = type(exc).__name__
            if isinstance(exc, RelayHTTPError):
                record['http_status'] = exc.status
                raise RelayHTTPError(exc.status) from None
            if isinstance(exc, (RelayError, ValueError)):
                # Even injected transports are not allowed to echo secret text.
                raise RelayOutcomeUncertain('relay request failed; no automatic retry') from None
            raise RelayOutcomeUncertain('transport exception; no automatic retry') from None
        finally:
            record['latency_seconds'] = time.monotonic() - started

    def verify_exact_model(self):
        response, record = self._call('https://' + ALLOWED_HOST + '/v1/models', 'GET', None, 'model_discovery')
        models = response.get('data')
        if not isinstance(models, list) or not any(isinstance(m, dict) and m.get('id') == EXACT_MODEL for m in models):
            raise ExactModelUnavailable('exact requested model absent from relay model listing')
        self.model_available = True
        evidence = {'source': 'relay_model_listing', 'model': EXACT_MODEL,
                    'backend_identity_independently_verified': False}
        self.model_evidence.append(evidence)
        return evidence

    def complete(self, messages, tools):
        self.last_usage = None
        if not self.model_available:
            raise ExactModelUnavailable('verify exact model listing before generation')
        from shopping_grpo.evaluation.rollout import _response_message, _responses_input, _responses_tools
        responses = self.endpoint.endswith('/responses')
        payload = {'model': EXACT_MODEL}
        if responses:
            payload.update(input=_responses_input(messages), max_output_tokens=self.max_output_tokens,
                           tools=_responses_tools(tools))
        else:
            payload.update(messages=messages, max_tokens=self.max_output_tokens,
                           tools=tools, temperature=0.0)
        if tools:
            payload['tool_choice'] = 'auto'
        response, record = self._call(self.endpoint, 'POST', payload, 'generation')
        returned_model = response.get('model')
        if returned_model != EXACT_MODEL:
            record['status'] = 'model_mismatch'
            self.accounting.frozen = True
            raise ExactModelUnavailable('response model ID differs from exact requested model; stopped')
        usage = response.get('usage') or {}
        self.last_usage = {'input_tokens': None, 'output_tokens': None, 'cost_usd': None}
        for target, source in [('input_tokens', 'input_tokens' if responses else 'prompt_tokens'),
                               ('output_tokens', 'output_tokens' if responses else 'completion_tokens')]:
            value = usage.get(source)
            if type(value) is int and value >= 0:
                self.last_usage[target] = record[target] = value
        self.model_evidence.append({'source': 'relay_generation_response', 'model': returned_model,
                                   'backend_identity_independently_verified': False})
        try:
            return _response_message(response, responses_api=responses)
        except (KeyError, TypeError, IndexError):
            raise RelayOutcomeUncertain('malformed assistant response; no retry') from None
