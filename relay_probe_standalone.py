#!/usr/bin/env python3
"""Candidate relay API probe, Python 3.10+ stdlib; no key storage or datasets.

Run in a real interactive terminal. Paste the key ONLY at the hidden prompt.
At most 2 HTTPS requests; no redirects, automatic retries, or model fallback.
The 30s socket inactivity timeout is not a hard overall completion deadline.
Relay-reported model IDs do not independently establish backend identity.
"""
import argparse
import getpass
import json
import sys
import warnings
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

HOST = 'st.walkcoding.top'
MODEL = 'gpt-6.1-sol'
ENDPOINTS = {
    'chat': 'https://st.walkcoding.top/v1/chat/completions',
    'responses': 'https://st.walkcoding.top/v1/responses',
}


class ProbeError(Exception):
    def __init__(self, kind, status=None):
        self.kind, self.status = kind, status
        super().__init__(kind)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProbeError('redirect_rejected')


def request(url, method, payload, key):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != HOST or
        parsed.port not in (None, 443) or parsed.username or parsed.password or
        parsed.query or parsed.fragment or parsed.path not in
        {'/v1/models', '/v1/chat/completions', '/v1/responses'}):
        raise ProbeError('unapproved_endpoint')
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    req = Request(url, data=data, method=method,
                  headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        with build_opener(NoRedirect()).open(req, timeout=30) as response:
            if response.geturl() != url:
                raise ProbeError('response_url_mismatch')
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ProbeError('response_too_large_billing_unknown')
            decoded = json.loads(raw)
    except HTTPError as exc:
        status = exc.code
        exc.close()  # Do not read/print error bodies or headers.
        raise ProbeError('http_error_billing_unknown', status) from None
    except ProbeError:
        raise
    except (URLError, OSError, TimeoutError):
        raise ProbeError('transport_outcome_unknown_no_retry') from None
    except (ValueError, UnicodeError):
        raise ProbeError('invalid_json_billing_unknown') from None
    if not isinstance(decoded, dict):
        raise ProbeError('invalid_response_shape')
    if key in json.dumps(decoded, ensure_ascii=False):
        raise ProbeError('credential_reflection_response_discarded')
    return decoded


def run_probe(key, endpoint='chat', transport=request):
    """Testable with an inert fixture transport; never writes a file."""
    result = {'success': False, 'model': MODEL, 'candidate_endpoint': ENDPOINTS[endpoint],
              'physical_attempts': 0, 'automatic_retries': 0, 'dataset_sent': False,
              'backend_identity_independently_verified': False,
              'billing_verified': False, 'cost_usd': None}
    try:
        if not isinstance(key, str) or not key or any(c.isspace() for c in key):
            raise ProbeError('invalid_transient_key')
        result['physical_attempts'] += 1
        listing = transport('https://' + HOST + '/v1/models', 'GET', None, key)
        models = listing.get('data')
        if not isinstance(models, list) or not any(isinstance(x, dict) and x.get('id') == MODEL for x in models):
            raise ProbeError('exact_model_not_listed_no_substitution')
        result['exact_model_listed'] = True
        if endpoint == 'chat':
            payload = {'model': MODEL, 'messages': [{'role': 'user', 'content': 'Reply with the single word OK.'}],
                       'max_tokens': 64, 'temperature': 0}
        else:
            payload = {'model': MODEL, 'input': 'Reply with the single word OK.', 'max_output_tokens': 64}
        result['physical_attempts'] += 1
        response = transport(ENDPOINTS[endpoint], 'POST', payload, key)
        if response.get('model') != MODEL:
            raise ProbeError('response_model_mismatch_no_substitution')
        result['exact_response_model'] = True
        if endpoint == 'chat':
            message = response['choices'][0]['message']
            text = message.get('content')
        else:
            text = ''.join(c.get('text', '') for item in response.get('output', [])
                           if item.get('type') == 'message' for c in item.get('content', [])
                           if c.get('type') in {'output_text', 'text'})
        if not isinstance(text, str) or not text.strip():
            raise ProbeError('empty_smoke_response')
        # Do not output generated text or arbitrary response metadata.
        usage = response.get('usage') or {}
        for target, source in [('input_tokens', 'prompt_tokens' if endpoint == 'chat' else 'input_tokens'),
                               ('output_tokens', 'completion_tokens' if endpoint == 'chat' else 'output_tokens')]:
            value = usage.get(source)
            result[target] = value if type(value) is int and value >= 0 else None
        result['success'] = True
    except ProbeError as exc:
        result['error_type'] = exc.kind
        if exc.status is not None:
            result['http_status'] = exc.status
    except Exception:
        result['error_type'] = 'response_or_transport_error_no_retry'
    finally:
        key = None
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint', choices=ENDPOINTS, default='chat',
                        help='Explicit candidate API; never try another automatically')
    args = parser.parse_args(argv)
    key = None
    try:
        if not sys.stdin.isatty():
            raise ProbeError('interactive_terminal_required_no_stdin_fallback')
        print('Connectivity probe only: exact gpt-6.1-sol, at most two requests, no dataset/evaluation.')
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            key = getpass.getpass('Relay API key (hidden, not saved): ')
        result = run_probe(key, args.endpoint)
    except KeyboardInterrupt:
        result = {'success': False, 'error_type': 'interrupted_no_automatic_retry'}
    except Exception:
        result = {'success': False, 'error_type': 'secure_terminal_input_unavailable'}
    finally:
        key = None
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result['success'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
