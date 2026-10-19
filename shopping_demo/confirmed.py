"""Human-operated offline product flow over the existing confirmed ABC runner.

The finite query fixtures below are visible in the UI. This is NOT an NLU model.
No endpoint, credential, marketplace adapter or arbitrary output path is accepted.
"""
from copy import deepcopy
import json
from pathlib import Path
import secrets

from evaluation.confirmed_demo import QUERY, SyntheticStore, fixture_client, fixture_proposal, fixture_response
from evaluation.confirmed_intent import (LLMProposalProvider, REVIEW_STATEMENT,
    prepare_intent, clarify_budget, confirm_intent, validate_confirmation)
from evaluation.confirmed_runner import run_confirmed_comparison
from evaluation.replay import verify_gate_replay

APPROXIMATE_QUERY = '我想买黑色耳机，大约花100元人民币。'
MISSING_BUDGET_QUERY = '帮我挑一副黑色耳机。'
UNSUPPORTED_QUERY = '帮我挑一副可以潜水的黑色耳机，最多花100元人民币。'
EXAMPLES = [QUERY, APPROXIMATE_QUERY, MISSING_BUDGET_QUERY, UNSUPPORTED_QUERY]
SCENARIOS = {'recovery': '改选黑色后满足已确认要求', 'variant_price': '黑色规格变为129元',
             'variant_unknown': '改选黑色后价格未知'}


def _transport(endpoint, payload, headers, timeout):
    if payload.get('response_format'):
        query = json.loads(payload['messages'][-1]['content'])['query']
        proposal = fixture_proposal(query)
        if query == APPROXIMATE_QUERY:
            proposal['budget'].update(classification='approximate_target', comparator='target', approximate=True)
        elif query == MISSING_BUDGET_QUERY:
            proposal['budget'].update(classification='absent', amounts=[], currency=None,
                                     comparator=None, approximate=None, source_spans=[])
        elif query == UNSUPPORTED_QUERY:
            proposal['predicates'].append({'kind': 'function', 'key': 'diving', 'operator': 'requires',
                'values': ['可以潜水'], 'unit': None, 'strength': 'hard', 'source_spans': [0]})
        elif query != QUERY:
            proposal['segments'][0]['role'] = 'unresolved'
            proposal['predicates'] = [{'kind': 'unknown', 'key': 'uninterpreted_query', 'operator': 'unknown',
                'values': [], 'unit': None, 'strength': 'uncertain', 'source_spans': [0]}]
            proposal['budget'].update(classification='absent', amounts=[], currency=None,
                                     comparator=None, approximate=None, source_spans=[])
        message = {'role': 'assistant', 'content': json.dumps(proposal, ensure_ascii=False)}
    else:
        feedback = payload['messages'][-1].get('content') or ''
        if 'Evidence gate rejected' in feedback:
            if 'over_budget' in feedback or 'price_unknown' in feedback:
                name, args = 'finish_without_purchase', {'reason': 'no_suitable_product'}
            else:
                name, args = 'select_option', {'value': '黑色'}
        else:
            name, args = 'buy_now', {}
        message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'offline-product-action',
            'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}
    return fixture_response(message, payload['model'])


class _Store(SyntheticStore):
    def __init__(self, query, scenario, **kwargs):
        super().__init__(**kwargs)
        self.query, self.scenario = query, scenario

    def reset(self, task_id):
        return {**super().reset(task_id), 'instruction': self.query}

    def state(self):
        value = super().state()
        if self.color == '黑色':
            if self.scenario == 'variant_price':
                value['selected_price'] = '129'
            elif self.scenario == 'variant_unknown':
                value['selected_price'] = None
        return value

    def step(self, action):
        if action == 'finish[no_suitable_product]':
            self.actions.append(action)
            return {'done': True, 'over': True, 'reward': 0,
                'observation_state': {'observation_version': 'shopping-observation-v2',
                    'page_type': 'terminal', 'search_available': False, 'actions': []}}
        return super().step(action)


class ConfirmedProduct:
    """Session-owned state machine. Snapshots are copies; approvals are frozen JSON."""
    def __init__(self, query, scenario='recovery'):
        if type(query) is not str or not query.strip() or len(query) > 256 or scenario not in SCENARIOS:
            raise ValueError('invalid offline input')
        self.revision = secrets.token_hex(16)
        self.scenario = scenario
        self.client = fixture_client(_transport, max_requests=13)
        self._review_json = json.dumps(prepare_intent(query, LLMProposalProvider(self.client)), ensure_ascii=False)
        self._confirmation_json = None
        self._result_json = None
        self._status = self.review()['state']

    def review(self):
        return json.loads(self._review_json)

    def _check_revision(self, revision):
        if type(revision) is not str or revision != self.revision:
            raise ValueError('stale_revision')

    def clarify(self, revision, ceiling_cny):
        self._check_revision(revision)
        if self._status != 'needs_clarification':
            raise ValueError('new_intake_required')
        updated = clarify_budget(self.review(), ceiling_cny)
        self._review_json = json.dumps(updated, ensure_ascii=False)
        self.revision = secrets.token_hex(16)
        self._status = updated['state']

    def confirm(self, revision, review_sha256, accepted):
        self._check_revision(revision)
        review = self.review()
        if self._status != 'awaiting_confirmation' or accepted is not True or review_sha256 != review['review_sha256']:
            raise ValueError('explicit_current_review_required')
        confirmed = confirm_intent(review, statement=REVIEW_STATEMENT, reviewer='interactive_offline_web_operator')
        self._confirmation_json = json.dumps(confirmed, ensure_ascii=False)
        self._status = 'confirmed'

    def run(self, revision, output_root):
        self._check_revision(revision)
        if self._status != 'confirmed':
            raise ValueError('confirm_before_run_or_create_new_intake')
        confirmed = json.loads(self._confirmation_json)
        validate_confirmation(confirmed)
        self._status = 'running'  # Even failure cannot reuse this approval.
        try:
            result = run_confirmed_comparison(1, confirmed, self.client, max_steps=4,
                max_model_calls_per_arm=5, env_factory=lambda **k: _Store(self.review()['original_query'], self.scenario, **k),
                output_dir=Path(output_root) / self.revision)
            self._result_json = json.dumps(result, ensure_ascii=False)
            self._status = 'finished'
        except Exception:
            self._status = 'failed'
            raise ValueError('offline_execution_failed') from None
        finally:
            self.client.close()

    def trace(self):
        if self._result_json is None:
            raise ValueError('trace_not_ready')
        return json.loads(self._result_json)

    def replay(self, revision):
        self._check_revision(revision)
        result = self.trace()
        row = next(r for r in result['rows'] if r['arm'] == 'C')
        return verify_gate_replay(row)

    def state(self):
        result = self.trace() if self._result_json else None
        return {'revision': self.revision, 'status': self._status, 'scenario': self.scenario,
            'review': self.review(), 'confirmation': json.loads(self._confirmation_json) if self._confirmation_json else None,
            'summary': deepcopy(result['summary']) if result else None,
            'c_outcome': self._outcome(result) if result else None,
            'offline_only': True, 'finite_query_fixtures': EXAMPLES.copy(),
            'scenarios': SCENARIOS.copy(), 'confirmation_statement': REVIEW_STATEMENT}

    @staticmethod
    def _outcome(result):
        row = next(r for r in result['rows'] if r['arm'] == 'C')
        return {'terminal_status': row['trajectory']['status'], 'purchased': row['purchased'],
            'purchase_outcome_unknown': row['purchase_outcome_unknown'],
            'gate_rejections': sum(e['executed'] is False for e in row['gate_events']),
            'confirmed_task_success': None, 'decision_calls': row['decision_model_calls'],
            'total_calls_including_proposal': row['model_calls']}
