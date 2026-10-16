"""Payload-free, observational failure tags for manifest-bound offline runs.

These tags describe recorded events, not causal attribution, semantic correctness,
or an independently adjudicated gate false-rejection rate. Never export arbitrary
query, observation, exception, or gate-reason strings into the public projection.
"""
from collections import Counter

from .experiment import complete_results


_STATUSES = frozenset({
    'done', 'max_steps', 'model_call_budget', 'assistant_final',
    'invalid_action_limit', 'error', 'setup_or_runner_error',
    'environment_release_failed', 'missing', 'aborted_unattempted',
})


def _reason_category(reason):
    if not isinstance(reason, str):
        return 'other_guard_requirement'
    if reason.startswith('query:') or reason == 'budget_unknown':
        return 'unsupported_or_ambiguous_query'
    if reason in {'price_unknown', 'observation:current_price_unknown'}:
        return 'missing_current_price_evidence'
    if reason.startswith('spec_unproven:'):
        return 'unproven_requirement'
    if reason == 'over_budget':
        return 'over_budget'
    if reason.startswith('intended_'):
        return 'intended_candidate_mismatch'
    return 'other_guard_requirement'


def analyze_failures(rows, *, manifest):
    """Keep every expected slot, including missing/error rows, without payloads."""
    completed, missing = complete_results(rows, manifest)
    cases = []
    totals = Counter()
    by_arm = {arm: Counter() for arm in manifest.arms}
    for row in completed:
        status = row['trajectory']['status']
        status = status if status in _STATUSES else 'other_status'
        gates = row.get('gate_events') or []
        rejected = [event for event in gates if event.get('executed') is False]
        categories = sorted({_reason_category(reason) for event in rejected
                             for reason in event.get('decision', {}).get('reasons', [])})
        tags = []
        if row['success']:
            outcome = 'strict_success'
            if rejected:
                tags.append('success_after_gate_rejection')
        elif row['wrong_purchase'] is True:
            outcome = 'known_wrong_purchase'
            tags.append('known_wrong_purchase')
        elif row.get('purchase_outcome_unknown'):
            outcome = 'purchase_outcome_unknown'
            tags.append('purchase_outcome_unknown')
        elif row['purchased']:
            outcome = 'purchased_without_strict_success'
            tags.append('purchased_without_strict_success')
        else:
            outcome = 'no_purchase'
        if row.get('parser') is not None and not row['parser_ready']:
            tags.append('parser_not_ready')
        if rejected:
            tags.append('gate_rejected')
            tags.extend(categories)
        if status in {'max_steps', 'model_call_budget'}:
            tags.append('bounded_budget_exhausted')
            if rejected:
                tags.append('gate_rejection_without_recovery')
        if status in {'missing', 'aborted_unattempted'}:
            tags.append('missing_or_unattempted_slot')
        if status in {'error', 'setup_or_runner_error', 'environment_release_failed'}:
            tags.append('execution_error')
        tags = sorted(set(tags))
        totals.update(tags)
        by_arm[row['arm']].update(tags)
        cases.append({
            'task_id': row['task_id'], 'arm': row['arm'], 'status': status,
            'outcome': outcome, 'tags': tags,
            'parser_ready': bool(row['parser_ready']) if row.get('parser') is not None else None,
            'gate_attempts': len(gates), 'gate_rejections': len(rejected),
            'budget_steps': row['budget_steps'], 'executed_steps': row['executed_steps'],
            'scripted_actor_calls': row['model_calls'],
        })
    return {
        'schema_version': 'offline-fixture-failure-analysis-v1',
        'execution_kind': manifest.config.execution_kind,
        'expected_rows': len(manifest.schedule()), 'analyzed_rows': len(cases),
        'missing_rows': len(missing), 'tag_counts': dict(sorted(totals.items())),
        'by_arm': {arm: dict(sorted(counts.items())) for arm, counts in by_arm.items()},
        'cases': cases, 'gate_false_rejection_rate': None,
        'limitations': [
            'Tags are observational, not causal or a real-model failure estimate.',
            'Private scripted terminal labels do not independently adjudicate rejected attempts.',
            'An evidence rejection does not establish that the candidate is actually wrong.',
        ],
        'contains_queries_observations_or_private_labels': False,
    }
