"""One exact-model authenticated connectivity probe, with no-echo transient key.

No dataset/simulator/GPU is needed. This verifies relay-reported IDs only, not
backend model authenticity. Unknown endpoints fail closed without substitution
or automatic retry. Do not pass keys through argv, env, files or tool calls.
"""
import argparse
import json
from pathlib import Path
from .credentials import read_transient_key
from .relay import RelayClient, AttemptAccounting, EXACT_MODEL


def probe(*, endpoint, key_reader=read_transient_key, transport=None):
    key = None
    client = None
    accounting = AttemptAccounting(2, max_wall_seconds=300)
    result = {'model':EXACT_MODEL, 'endpoint':endpoint, 'success':False,
              'backend_identity_independently_verified':False, 'billing_verified':False,
              'cost_usd':None, 'dataset_sent':False}
    try:
        key = key_reader()
        kwargs = {'transport':transport} if transport is not None else {}
        client = RelayClient(api_key=key,endpoint=endpoint,accounting=accounting,
                             max_output_tokens=64,timeout=30,**kwargs)
        key = None
        result['listing'] = client.verify_exact_model()
        message = client.complete([{'role':'user','content':'Reply with the single word OK.'}],[])
        result['response_received'] = True
        result['nonempty_text'] = bool(message.get('content'))
        result['success'] = True
        result['model_evidence'] = client.model_evidence
        result['usage'] = client.last_usage
    except Exception as exc:
        # Never return raw exception text, requests, response body or credentials.
        result['error_type'] = type(exc).__name__
        if hasattr(exc,'status'): result['http_status'] = exc.status
    finally:
        key = None
        if client is not None: client.close()
        result['physical_attempts'] = len(accounting.records)
        result['request_accounting'] = accounting.records
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint', required=True, choices=[
        'https://st.walkcoding.top/v1/chat/completions','https://st.walkcoding.top/v1/responses'])
    parser.add_argument('--probe-authorized', action='store_true')
    args=parser.parse_args(argv)
    if not args.probe_authorized:
        parser.error('explicit --probe-authorized required; this sends at most two authenticated requests')
    result=probe(endpoint=args.endpoint)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0 if result['success'] else 2

if __name__=='__main__':raise SystemExit(main())
