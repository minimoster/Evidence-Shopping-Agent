"""Bounded interactive evaluator: credentials are entered with no-echo getpass.

Default is offline preflight. Actual requests require --execute-authorized and
--no-monetary-cap plus a real controlling terminal. Never provide the key via
CLI arguments, environment variables, files, redirected stdin, or tool calls.
This entrypoint must only be run in the user's explicitly selected environment.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict, replace
import getpass
import json
from pathlib import Path
import sys
import warnings

from .authorization import RealRunScope
from .credentials import read_transient_key
from .experiment import load_development_manifest, incomplete_row
from .runner import RunConfig, run_task, write_trace
from .relay import RelayClient, AttemptAccounting, EXACT_MODEL, _validate_url
from .report import summarize

# Current natural-language dev coverage is 0/20. Only connectivity probing is
# released; a full paid comparison needs semantic-compiler review first.
EVALUATION_EXECUTION_RELEASED = False


def run_authorized(plan, runtime, client, output_dir):
    """Run discovery + one small smoke + exactly the planned bounded task slots.

    No uncertain request retry. Infrastructure/model errors stop new task slots;
    all remaining expected rows are recorded as unattempted, not discarded.
    """
    if plan.config.execution_kind != 'real_model_real_simulator':
        raise ValueError('real execution manifest required')
    scope = RealRunScope(plan.task_ids)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=False)
    write_trace(directory / 'manifest.json', plan.to_dict())
    rows = []
    stop = None
    try:
        evidence = client.verify_exact_model()
        previous_limit = client.max_output_tokens
        client.max_output_tokens = 64
        try:
            smoke = client.complete([{'role':'user','content':'Reply with the single word OK.'}], [])
        finally:
            client.max_output_tokens = previous_limit
        # A successful exact-ID response proves connectivity, not backend identity.
        write_trace(directory / 'connectivity.json', {
            'model': EXACT_MODEL, 'listing': evidence, 'response_received': True,
            'nonempty_text': bool(smoke.get('content')), 'model_evidence': client.model_evidence,
            'backend_identity_independently_verified': False})
        for task_id, arm in plan.schedule():
            if stop is not None:
                row = incomplete_row(plan, task_id, arm, status='aborted_unattempted', error_type=stop)
                row['purchase_outcome_unknown'] = False
                row['measurement_complete'] = True  # Known not dispatched.
            else:
                try:
                    row = run_task(task_id, client, config=replace(plan.config, arm=arm),
                                   env_factory=runtime.env_factory, real_scope=scope)
                    row['experiment_sha256'] = plan.sha256
                    row['measurement_complete'] = True
                    status = row['trajectory']['status']
                    if client.accounting.frozen or status in {'error', 'environment_release_failed'}:
                        stop = (row['trajectory'].get('error') or {}).get('type') or status
                except Exception as exc:
                    stop = type(exc).__name__
                    row = incomplete_row(plan, task_id, arm, status='setup_or_runner_error', error_type=stop)
                    row['purchase_outcome_unknown'] = True
            rows.append(row)
            write_trace(directory / f'{task_id}-{arm}.json', row)
            print(json.dumps({'task_id':task_id,'arm':arm,'status':row['trajectory']['status'],
                              'success':row['success'],'model_calls':row['model_calls']}, ensure_ascii=False), flush=True)
    except Exception as exc:
        stop = type(exc).__name__
        # Includes model-discovery/smoke failure. No task is silently omitted.
        existing = {(r['task_id'],r['arm']) for r in rows}
        for task_id, arm in plan.schedule():
            if (task_id,arm) in existing: continue
            row = incomplete_row(plan, task_id, arm, status='aborted_unattempted', error_type=stop)
            row['purchase_outcome_unknown'] = False
            row['measurement_complete'] = True
            rows.append(row)
            write_trace(directory / f'{task_id}-{arm}.json', row)
    finally:
        client.close()
        try:
            runtime.close()
        except Exception as cleanup_error:
            stop = stop or type(cleanup_error).__name__
        write_trace(directory / 'request-accounting.json', {
            'model':EXACT_MODEL, 'records':client.accounting.records,
            'physical_attempts':len(client.accounting.records), 'max_attempts':client.accounting.max_attempts,
            'cost_usd':None, 'billing_verified':False, 'monetary_cap_usd':None,
            'automatic_retries':0, 'stop_reason':stop,
            'model_evidence':client.model_evidence,
            'backend_identity_independently_verified':False})
    report = summarize(rows, manifest=plan)
    report['stop_reason'] = stop
    report['monetary_cost_usd'] = None
    report['billing_verified'] = False
    write_trace(directory / 'report.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir', type=Path, required=True)
    parser.add_argument('--split-manifest', type=Path, default=Path('runtime/dev20/manifest.json'))
    parser.add_argument('--tasks', type=Path, default=Path('runtime/dev20/tasks.jsonl'))
    parser.add_argument('--endpoint', required=True, choices=[
        'https://st.walkcoding.top/v1/chat/completions','https://st.walkcoding.top/v1/responses'])
    parser.add_argument('--output-dir', type=Path, default=Path('results/dev20-real'))
    parser.add_argument('--execute-authorized', action='store_true')
    parser.add_argument('--no-monetary-cap', action='store_true')
    args = parser.parse_args(argv)
    _validate_url(args.endpoint)
    config = RunConfig(execution_kind='real_model_real_simulator')
    plan = load_development_manifest(args.split_manifest, args.tasks, config=config)
    from .local_simulator import LocalSimulatorRuntime
    runtime = LocalSimulatorRuntime(runtime_dir=args.runtime_dir, split_dir=args.split_manifest.parent)
    key = None
    client = None
    try:
        if not runtime.verified or tuple(runtime.task_ids) != plan.task_ids:
            raise ValueError('pinned simulator verification or development-ID binding failed')
        if not args.execute_authorized:
            print(json.dumps({'status':'offline_preflight_only','tasks':20,'task_arm_slots':60,
                              'credential_requested':False,'model_requests':0}))
            return 0
        if not EVALUATION_EXECUTION_RELEASED:
            raise ValueError('full evaluation paused for semantic-compiler review; use standalone connectivity probe')
        if not args.no_monetary_cap:
            raise ValueError('this authorized plan has no monetary cap; explicit flag required')
        if args.output_dir.exists():
            raise ValueError('output directory exists; automatic resume is not supported')
        key = read_transient_key()
        # Discovery + smoke + 60 * 30 calls; no auto-retries.
        # 2h admission window, not a hard completion deadline for in-flight I/O.
        accounting = AttemptAccounting(1802, max_wall_seconds=7200)
        client = RelayClient(api_key=key, endpoint=args.endpoint, accounting=accounting)
        key = None
        result = run_authorized(plan, runtime, client, args.output_dir)
        return 1 if result['stop_reason'] else 0
    finally:
        key = None
        if client is not None: client.close()
        runtime.close()

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Never print exception text/tracebacks that may contain request details.
        print(json.dumps({'status':'blocked_or_failed','error_type':type(exc).__name__}), file=sys.stderr)
        raise SystemExit(2)
