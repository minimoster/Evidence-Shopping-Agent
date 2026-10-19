"""Opt-in SINGLE-task simulator intake and A/B/C run, not the dev20 experiment.

Default only validates explicit configuration and prints a preflight. Execution
needs a terminal, new network/spend authorization, verified local data and human
review. Never pass a credential as an argument or put it in the config file.
"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sys

from .confirmed_intent import LLMProposalProvider, prepare_intent, confirm_intent, REVIEW_STATEMENT, digest
from .confirmed_runner import ConfirmedComparisonScope, run_confirmed_comparison
from .credentials import read_transient_key
from .model_adapter import ModelConfig, ModelClient
from .runner import RunConfig, write_trace


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--runtime-dir', type=Path, required=True)
    parser.add_argument('--split-dir', type=Path, required=True)
    parser.add_argument('--task-id', type=int, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--max-steps', type=int, default=10)
    parser.add_argument('--max-model-calls-per-arm', type=int, default=10)
    parser.add_argument('--execute-authorized', action='store_true')
    parser.add_argument('--accept-quoted-reservation-risk', action='store_true',
                        help='acknowledge reservation is not a provider-enforced billing cap')
    args = parser.parse_args(argv)
    config = ModelConfig(**json.loads(args.config.read_text(encoding='utf-8')))
    RunConfig(max_steps=args.max_steps, max_model_calls=args.max_model_calls_per_arm)
    maximum = 1 + 3 * (args.max_model_calls_per_arm - 1)
    from decimal import Decimal
    if (args.task_id < 0 or args.max_model_calls_per_arm <= 1 or config.max_requests < maximum
            or Decimal(config.per_request_reserve_usd) * maximum > Decimal(config.max_reserved_usd)):
        raise ValueError('insufficient finite session budget for all three arms')
    print(json.dumps({'mode': 'preflight', 'model': config.model, 'endpoint': config.endpoint,
          'task_id': args.task_id, 'maximum_physical_requests': maximum,
          'proposal_charged_per_arm': True, 'provider_enforced_monetary_cap': False,
          'network_called': False}, ensure_ascii=False))
    if not args.execute_authorized:
        return 0
    if not args.accept_quoted_reservation_risk or not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError('new spend-risk acknowledgement and controlling terminal required')
    # Prevent pre-existing output from causing paid work with nowhere to save it.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    write_trace(args.output_dir / 'authorization.json', {'config': config.__dict__,
        'task_id': args.task_id, 'max_steps': args.max_steps,
        'max_model_calls_per_arm': args.max_model_calls_per_arm,
        'maximum_physical_requests': maximum, 'operator_network_opt_in': True,
        'reservation_is_not_billing_cap_acknowledged': True})
    try:
        from .local_simulator import LocalSimulatorRuntime
        with closing(LocalSimulatorRuntime(args.runtime_dir, split_dir=args.split_dir,
                                            log_dir=args.output_dir / 'simulator_logs')) as runtime:
            if args.task_id not in runtime.task_ids:
                raise ValueError('task outside verified development split')
            env = runtime.env_factory(base_url='http://127.0.0.1:5700')
            try:
                query = env.reset(args.task_id)['instruction']
            finally:
                env.release()
            key = read_transient_key()
            with closing(ModelClient(config, api_key=key, allow_network=True)) as client:
                key = None
                review = prepare_intent(query, LLMProposalProvider(client))
                write_trace(args.output_dir / 'review.json', review)
                print(json.dumps(review, ensure_ascii=False, indent=2))
                if review['state'] != 'awaiting_confirmation':
                    print('Clarification required; stopped without simulator actions. No automatic re-proposal.')
                    return 2
                print(REVIEW_STATEMENT)
                phrase = 'CONFIRM ' + review['review_sha256']
                if input('Type ' + phrase + ' to confirm and execute this simulator task: ') != phrase:
                    write_trace(args.output_dir / 'declined.json', {'state': 'not_confirmed'})
                    return 2
                confirmed = confirm_intent(review, statement=REVIEW_STATEMENT, reviewer='interactive_operator')
                write_trace(args.output_dir / 'confirmation.json', confirmed)
                scope = ConfirmedComparisonScope(args.task_id, confirmed['confirmation_sha256'],
                    digest(client.public_config()), args.max_steps, args.max_model_calls_per_arm)
                result = run_confirmed_comparison(args.task_id, confirmed, client,
                    max_steps=args.max_steps, max_model_calls_per_arm=args.max_model_calls_per_arm,
                    env_factory=runtime.env_factory, output_dir=args.output_dir / 'comparison', real_scope=scope)
                print(json.dumps(result['summary'], ensure_ascii=False, indent=2))
                return 1 if any(r['trajectory']['status'] in {
                    'error', 'setup_or_runner_error', 'environment_release_failed', 'aborted_unattempted'
                } for r in result['rows']) else 0
    except Exception as exc:
        write_trace(args.output_dir / 'failure.json', {'error_type': type(exc).__name__,
                    'outcome': 'inspect_persisted_review_and_arm_traces_no_automatic_retry'})
        print('Stopped: ' + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
