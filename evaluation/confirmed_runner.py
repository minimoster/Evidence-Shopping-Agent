"""Single-task, human-confirmed A/B/C comparison; no default execution.

One shared proposal is charged in full to EVERY arm's logical budget. Physical
requests are counted once in the session ledger. A/B retain their experimental
no-evidence-gate behavior and are restricted to simulator use. The same explicit
confirmation/readiness prerequisite applies to all three arms.
"""
from copy import deepcopy
from dataclasses import dataclass, asdict, replace
from decimal import Decimal
from pathlib import Path

from .confirmed_intent import validate_confirmation, digest
from .model_adapter import ModelClient
from .runner import RunConfig, run_task, write_trace


@dataclass(frozen=True)
class ConfirmedComparisonScope:
    """Records NEW operator approval for one simulator task, never inherited."""
    task_id: int
    confirmation_sha256: str
    model_config_sha256: str
    max_steps: int
    max_model_calls_per_arm: int

    def validate(self, task_id, config, confirmation, client):
        if (type(self.task_id) is not int or self.task_id < 0 or task_id != self.task_id
                or self.confirmation_sha256 != confirmation['confirmation_sha256']
                or self.model_config_sha256 != digest(client.public_config())
                or self.max_steps != config.max_steps
                or self.max_model_calls_per_arm != config.max_model_calls):
            raise ValueError('confirmed comparison differs from explicit scope')


def _failure(task_id, config, confirmation, status, error_type=None):
    usage = deepcopy(confirmation['review']['proposal_usage'])
    return {'schema_version': 'evidence-dev-evaluation-v1', 'task_id': task_id,
            'arm': config.arm, 'config': asdict(config), 'execution_kind': config.execution_kind,
            'confirmed_intent': deepcopy(confirmation), 'success': None, 'purchased': False,
            'wrong_purchase': None, 'original_task_success': None,
            'confirmed_task_success': None, 'confirmed_task_adjudication': 'not_available',
            'purchase_outcome_unknown': status == 'setup_or_runner_error',
            'proposal_model_calls': len(usage), 'decision_model_calls': 0,
            'model_calls': len(usage), 'usage': usage, 'measurement_complete': False,
            'gate_events': [], 'trajectory': {'status': status, 'steps': [],
            'error': {'type': error_type} if error_type else None}}


def run_confirmed_comparison(task_id, confirmation, client, *, max_steps,
                             max_model_calls_per_arm, env_factory, output_dir, real_scope=None):
    """Reuse the intake client, with fresh environment/collector for each arm.

    Exclusive artifacts persist the plan before any action; no automatic retry or
    resume. An interrupted run retains explicit pending rows. Ordinary failures
    retain all three denominator rows. No 20-task/60-run dispatcher is enabled.
    """
    validate_confirmation(confirmation)
    if type(task_id) is not int or task_id < 0 or type(client) is not ModelClient:
        raise ValueError('explicit task ID and bounded client required')
    review = confirmation['review']
    if client.public_config() != review['model_config'] or client.records != review['proposal_usage']:
        raise ValueError('reuse exactly the proposal session; no hidden calls or resumed session')
    config = RunConfig(max_steps=max_steps, max_model_calls=max_model_calls_per_arm,
                       execution_kind=client.execution_kind, intent_protocol='human_confirmed_v1')
    proposal_calls = len(review['proposal_usage'])
    if config.max_model_calls <= proposal_calls:
        raise ValueError('total per-arm budget leaves no decision request')
    maximum_physical = proposal_calls + 3 * (config.max_model_calls - proposal_calls)
    if (client.config.max_requests < maximum_physical or
            Decimal(client.config.per_request_reserve_usd) * maximum_physical > Decimal(client.config.max_reserved_usd)):
        raise ValueError('session limits cannot fund the same maximum budget for all three arms')
    if client.execution_kind != 'mocked_smoke':
        if type(real_scope) is not ConfirmedComparisonScope:
            raise ValueError('explicit new simulator scope required')
        real_scope.validate(task_id, config, confirmation, client)
        from .local_simulator import LocalSimulatorRuntime
        owner = getattr(env_factory, '__self__', None)
        if not isinstance(owner, LocalSimulatorRuntime) or not owner.verified:
            raise ValueError('verified pinned local simulator required')
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=False)
    plan = {'schema': 'confirmed-comparison-v1', 'task_id': task_id,
            'arms': ['A', 'B', 'C'], 'config': asdict(config),
            'model_config': client.public_config(), 'confirmation': deepcopy(confirmation),
            'maximum_physical_requests': maximum_physical,
            'proposal_accounting': 'shared_once_physically_full_charge_per_arm',
            'semantic_equivalence_verified': False, 'confirmed_task_success': None}
    write_trace(directory / 'plan.json', plan)
    rows = []
    # This file remains available even if KeyboardInterrupt prevents completion.
    write_trace(directory / 'pending.json', {'rows': [_failure(task_id, replace(config, arm=a),
                confirmation, 'pending_unattempted') for a in ('A', 'B', 'C')]})
    stopped = False
    for arm in ('A', 'B', 'C'):
        selected = replace(config, arm=arm)
        start = len(client.records)
        if client.frozen or stopped:
            row = _failure(task_id, selected, confirmation, 'aborted_unattempted')
        else:
            try:
                row = run_task(task_id, client, config=selected, env_factory=env_factory,
                               real_scope=real_scope, confirmed_intent=confirmation)
                row['measurement_complete'] = True
            except Exception as exc:
                row = _failure(task_id, selected, confirmation, 'setup_or_runner_error', type(exc).__name__)
        # Preserve physical requests even if a failure escapes the collector.
        row['physical_decision_usage'] = deepcopy(client.records[start:])
        if row['trajectory']['status'] == 'setup_or_runner_error':
            physical = row['physical_decision_usage']
            row['decision_model_calls'] = len(physical)
            row['model_calls'] = proposal_calls + len(physical)
            row['usage'] += physical
            row['logical_attempts_complete'] = False
        if row['trajectory']['status'] in {'error', 'setup_or_runner_error', 'environment_release_failed'}:
            stopped = True
        row['comparison_sha256'] = digest(plan)
        rows.append(row)
        write_trace(directory / (arm + '.json'), row)
    summary = {'schema': 'confirmed-comparison-summary-v1', 'expected_rows': 3,
               'execution_kind': client.execution_kind, 'confirmed_task_success_rate': None,
               'semantic_quality_measured': False,
               'original_gold_note': 'original_task_success scores original simulator task only; not confirmed-task success',
               'physical_requests': len(client.records), 'physical_usage': deepcopy(client.records),
               'reserved_usd': str(sum((Decimal(r['reserved_usd']) for r in client.records), Decimal(0))),
               'billed_cost_usd': None, 'proposal_accounting': plan['proposal_accounting'],
               'rows': [{'arm': r['arm'], 'status': r['trajectory']['status'], 'purchased': r['purchased'],
                         'original_task_success': r['original_task_success'],
                         'logical_model_calls': r['model_calls']} for r in rows]}
    write_trace(directory / 'summary.json', summary)
    return {'plan': plan, 'rows': rows, 'summary': summary}
