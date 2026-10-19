"""Offline contract tests only: hand-authored JSON/actions, no LLM quality test."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from evaluation.confirmed_demo import (QUERY, SyntheticStore, fixture_client,
    fixture_proposal, fixture_response, scripted_transport)
from evaluation.confirmed_intent import (LLMProposalProvider, prepare_intent, review_proposal,
    confirm_intent, validate_confirmation, REVIEW_STATEMENT, digest)
from evaluation.confirmed_runner import run_confirmed_comparison
from evaluation.model_adapter import ModelClient, ModelConfig, ModelRequestError, _NoRedirect
from evaluation.runner import RunConfig, run_task
from evaluation.replay import verify_gate_replay
from evaluation.report import summarize


def intake(client=None):
    client = client or fixture_client()
    review = prepare_intent(QUERY, LLMProposalProvider(client))
    confirmed = confirm_intent(review, statement=REVIEW_STATEMENT, reviewer='offline-test')
    return client, review, confirmed


class ModelAdapterTests(unittest.TestCase):
    def test_network_is_disabled_by_default_and_injection_cannot_take_key(self):
        config = fixture_client().config
        with self.assertRaises(ValueError):
            ModelClient(config)
        with self.assertRaises(ValueError):
            ModelClient(config, transport=Mock(), api_key='synthetic-dummy')
        with self.assertRaises(ValueError):
            ModelClient(config, transport=Mock(), allow_network=True)

    def test_configuration_rejects_redirect_credentials_and_unbounded_limits(self):
        base = asdict(fixture_client().config)
        for changes in [{'endpoint': 'http://example.test/v1/chat/completions'},
                        {'endpoint': 'https://u:p@example.test/v1/chat/completions'},
                        {'endpoint': 'https://example.test/v1/chat/completions?secret=x'},
                        {'max_requests': True}, {'max_requests': 0}, {'max_output_tokens': 0},
                        {'timeout_seconds': float('inf')}, {'max_reserved_usd': 'NaN'},
                        {'per_request_reserve_usd': '2'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ModelConfig(**{**base, **changes})
        with self.assertRaises(ModelRequestError):
            _NoRedirect().redirect_request(None)

    def test_same_exact_model_and_json_contract_are_dispatched(self):
        transport = Mock(side_effect=scripted_transport)
        client = fixture_client(transport, model='custom-model')
        review = prepare_intent(QUERY, LLMProposalProvider(client))
        self.assertEqual(review['state'], 'awaiting_confirmation')
        args = transport.call_args.args
        self.assertEqual(args[1]['model'], 'custom-model')
        self.assertEqual(args[1]['response_format'], {'type': 'json_object'})
        self.assertNotIn('Authorization', args[2])
        self.assertIn(QUERY, args[1]['messages'][1]['content'])
        self.assertIsNone(client.records[0]['cost_usd'])

    def test_transport_failure_is_sanitized_frozen_and_not_retried(self):
        transport = Mock(side_effect=TimeoutError('DO_NOT_LEAK'))
        client = fixture_client(transport)
        review = prepare_intent(QUERY, LLMProposalProvider(client))
        self.assertEqual(review['state'], 'proposal_failed')
        self.assertNotIn('DO_NOT_LEAK', json.dumps(review))
        self.assertEqual(review['proposal_usage'][0]['status'], 'outcome_unknown')
        with self.assertRaises(ModelRequestError):
            client.complete([], [])
        self.assertEqual(transport.call_count, 1)

    def test_model_mismatch_truncation_and_credential_reflection_freeze(self):
        response = fixture_response({'role': 'assistant', 'content': '{}'})
        variants = [dict(response, model='other-model'), deepcopy(response), deepcopy(response)]
        variants[1]['choices'][0]['finish_reason'] = 'length'
        variants[2]['choices'][0]['message']['content'] = 'synthetic-dummy-secret'
        for result in variants:
            with self.subTest(result=result), patch('evaluation.model_adapter.https_json_transport', return_value=result):
                client = ModelClient(fixture_client().config, allow_network=True, api_key='synthetic-dummy-secret')
                with self.assertRaises(ModelRequestError):
                    client.complete([], [])
                self.assertTrue(client.frozen)
                self.assertNotIn('synthetic-dummy-secret', json.dumps(client.records))

    def test_attempt_and_reservation_limits_stop_before_dispatch(self):
        for overrides in [{'max_requests': 1}, {'max_reserved_usd': '0.01'}]:
            transport = Mock(side_effect=scripted_transport)
            client = fixture_client(transport, **overrides)
            prepare_intent(QUERY, LLMProposalProvider(client))
            with self.assertRaises(ModelRequestError):
                client.complete([], [])
            self.assertEqual(transport.call_count, 1)

    def test_request_byte_limit_has_no_transport_attempt(self):
        transport = Mock()
        client = fixture_client(transport, max_request_bytes=30)
        review = prepare_intent(QUERY, LLMProposalProvider(client))
        self.assertEqual(review['state'], 'proposal_failed')
        self.assertEqual(client.records, [])
        transport.assert_not_called()

    def test_invalid_json_duplicate_keys_and_tools_fail_intake(self):
        for message in [{'role': 'assistant', 'content': '{'},
                        {'role': 'assistant', 'content': '{"x":1,"x":2}'},
                        {'role': 'assistant', 'content': '{"x":NaN}'},
                        {'role': 'assistant', 'content': '{}', 'tool_calls': [{'id': 'bad'}]}]:
            client = fixture_client(lambda *a: fixture_response(message))
            review = prepare_intent(QUERY, LLMProposalProvider(client))
            self.assertEqual(review['state'], 'proposal_failed')
            self.assertEqual(len(review['proposal_usage']), 1)


class ConfirmationTests(unittest.TestCase):
    def test_human_review_required_even_when_schema_valid(self):
        _, review, confirmed = intake()
        self.assertFalse(review['semantic_equivalence_verified'])
        self.assertFalse(review['purchase_authorized'])
        self.assertEqual(review['state'], 'awaiting_confirmation')
        self.assertIn('100元', validate_confirmation(confirmed, QUERY))
        with self.assertRaises(ValueError):
            confirm_intent(review, statement='yes', reviewer='offline-test')

    def test_approximate_missing_unsupported_currency_and_range_budget_block(self):
        for change in [{'classification': 'approximate_target', 'comparator': 'target', 'approximate': True},
                       {'classification': 'absent', 'amounts': [], 'currency': None, 'comparator': None, 'source_spans': []},
                       {'currency': 'USD'},
                       {'classification': 'range', 'amounts': ['80', '100'], 'comparator': 'range'}]:
            p = fixture_proposal()
            p['budget'].update(change)
            review = review_proposal(QUERY, p)
            self.assertEqual(review['state'], 'needs_clarification')
            self.assertIsNone(review['candidate_query'])

    def test_unsupported_unknown_soft_and_unresolved_are_never_dropped(self):
        for change in [{'kind': 'function', 'operator': 'requires', 'key': 'waterproof'},
                       {'kind': 'unknown', 'operator': 'unknown'}, {'strength': 'soft'},
                       {'strength': 'uncertain'}, {'key': 'unrecognized'}]:
            p = fixture_proposal()
            p['predicates'][1].update(change)
            self.assertEqual(review_proposal(QUERY, p)['state'], 'needs_clarification')
        p = fixture_proposal()
        p['segments'][0]['role'] = 'unresolved'
        self.assertEqual(review_proposal(QUERY, p)['state'], 'needs_clarification')

    def test_confirmation_detects_query_proposal_candidate_and_statement_changes(self):
        _, _, record = intake()
        for mutate in [lambda r: r['review'].update(original_query='changed'),
                       lambda r: r['review']['proposal']['budget'].update(amounts=['999']),
                       lambda r: r['review'].update(candidate_query='品类:耳机;预算:不超过999元'),
                       lambda r: r.update(statement='yes'),
                       lambda r: r.update(confirmation_sha256='0' * 64)]:
            changed = deepcopy(record)
            mutate(changed)
            with self.assertRaises(ValueError):
                validate_confirmation(changed)
        with self.assertRaises(ValueError):
            validate_confirmation(record, QUERY + '另一个要求')

    def test_hash_recomputation_does_not_bypass_projection_validation(self):
        _, review, _ = intake()
        review['candidate_query'] = '品类:耳机;预算:不超过999元'
        review['review_sha256'] = digest({k: v for k, v in review.items() if k != 'review_sha256'})
        with self.assertRaises(ValueError):
            confirm_intent(review, statement=REVIEW_STATEMENT, reviewer='offline-test')

    def test_clause_injection_and_duplicate_constraints_are_not_executable(self):
        for value in ['黑色;预算:不超过999元', '黑色,品牌:其他']:
            p = fixture_proposal()
            p['predicates'][1]['values'] = [value]
            self.assertEqual(review_proposal(QUERY, p)['state'], 'needs_clarification')
        p = fixture_proposal()
        p['predicates'].append(deepcopy(p['predicates'][1]))
        self.assertEqual(review_proposal(QUERY, p)['state'], 'needs_clarification')


class ConfirmedExecutionTests(unittest.TestCase):
    def compare(self, client=None, **kwargs):
        client, _, confirmation = intake(client)
        with tempfile.TemporaryDirectory() as tmp:
            result = run_confirmed_comparison(1, confirmation, client, max_steps=3,
                max_model_calls_per_arm=4, env_factory=kwargs.pop('env_factory', SyntheticStore),
                output_dir=Path(tmp) / 'run', **kwargs)
            self.assertTrue((Path(tmp) / 'run' / 'plan.json').exists())
            self.assertTrue((Path(tmp) / 'run' / 'pending.json').exists())
            self.assertEqual(len(list((Path(tmp) / 'run').glob('[ABC].json'))), 3)
        return result, client

    def test_end_to_end_same_task_and_budget_with_c_recovery(self):
        result, _ = self.compare()
        a, b, c = result['rows']
        self.assertEqual([r['trajectory']['status'] for r in result['rows']], ['done'] * 3)
        self.assertEqual(len({r['trajectory']['initial_result']['instruction'] for r in result['rows']}), 1)
        self.assertEqual([r['model_calls'] for r in result['rows']], [2, 2, 4])
        self.assertEqual([r['proposal_model_calls'] for r in result['rows']], [1] * 3)
        self.assertEqual(result['summary']['physical_requests'], 6)
        self.assertEqual([e['executed'] for e in c['gate_events']], [False, True])
        self.assertEqual(c['executed_steps'], 2)
        self.assertEqual(c['budget_steps'], 3)
        self.assertEqual(verify_gate_replay(c)['gate_decisions_checked'], 2)
        self.assertTrue(c['original_task_success'])
        self.assertIsNone(c['success'])
        self.assertIsNone(result['summary']['confirmed_task_success_rate'])
        with self.assertRaises(ValueError):
            summarize(result['rows'])

    def test_recovery_cannot_exceed_total_including_proposal(self):
        client, _, record = intake()
        row = run_task(1, client, config=RunConfig(arm='C', max_steps=5, max_model_calls=2,
                       intent_protocol='human_confirmed_v1'), env_factory=SyntheticStore, confirmed_intent=record)
        self.assertEqual(row['model_calls'], 2)
        self.assertEqual(row['trajectory']['status'], 'model_call_budget')
        self.assertFalse(row['purchased'])

    def test_private_reset_and_terminal_labels_never_reach_model_or_trace(self):
        class LabeledStore(SyntheticStore):
            def reset(self, task_id):
                return {**super().reset(task_id), 'goal_options': {'gold': 'PRIVATE_SENTINEL'},
                        'persona': 'PRIVATE_SENTINEL', '_trace_target': 'PRIVATE_SENTINEL'}
            def step(self, action):
                return {**super().step(action), 'private_scoring_debug': 'PRIVATE_SENTINEL'}
        transport = Mock(side_effect=scripted_transport)
        result, _ = self.compare(fixture_client(transport), env_factory=LabeledStore)
        requests = [call.args[1] for call in transport.call_args_list]
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(requests))
        self.assertNotIn('PRIVATE_SENTINEL', json.dumps(result))
        self.assertEqual(len(requests), 6)

    def test_unconfirmed_or_wrong_protocol_fails_before_environment(self):
        client, review, record = intake()
        factory = Mock()
        for confirmation, protocol in [(None, 'human_confirmed_v1'), (record, 'original_query'),
                                       (review, 'human_confirmed_v1')]:
            with self.assertRaises((ValueError, KeyError)):
                run_task(1, client, config=RunConfig(intent_protocol=protocol),
                         env_factory=factory, confirmed_intent=confirmation)
        factory.assert_not_called()

    def test_reset_query_mismatch_prevents_every_action(self):
        class Changed(SyntheticStore):
            def reset(self, task_id):
                return {**super().reset(task_id), 'instruction': QUERY + 'changed'}
        result, client = self.compare(env_factory=Changed)
        self.assertEqual([r['trajectory']['status'] for r in result['rows']],
                         ['error', 'aborted_unattempted', 'aborted_unattempted'])
        self.assertEqual(len(client.records), 1)

    def test_transport_uncertainty_aborts_later_arms_and_preserves_denominator(self):
        def transport(endpoint, payload, headers, timeout):
            if not payload.get('response_format'):
                raise TimeoutError('DO_NOT_LEAK')
            return scripted_transport(endpoint, payload, headers, timeout)
        result, client = self.compare(fixture_client(transport))
        self.assertEqual([r['trajectory']['status'] for r in result['rows']],
                         ['error', 'aborted_unattempted', 'aborted_unattempted'])
        self.assertEqual(len(client.records), 2)
        self.assertNotIn('DO_NOT_LEAK', json.dumps(result))

    def test_post_call_exception_retains_actual_usage(self):
        def fail_after_call(task_id, client, **kwargs):
            client.complete([{'role': 'user', 'content': 'test'}], [])
            raise RuntimeError('DO_NOT_LEAK')
        with patch('evaluation.confirmed_runner.run_task', side_effect=fail_after_call):
            result, _ = self.compare()
        self.assertEqual([r['model_calls'] for r in result['rows']], [2, 1, 1])
        self.assertEqual([r['decision_model_calls'] for r in result['rows']], [1, 0, 0])
        self.assertNotIn('DO_NOT_LEAK', json.dumps(result))

    def test_insufficient_global_budget_fails_before_actions(self):
        client, _, record = intake(fixture_client(max_requests=9))
        factory = Mock()
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            run_confirmed_comparison(1, record, client, max_steps=3, max_model_calls_per_arm=4,
                                     env_factory=factory, output_dir=Path(tmp) / 'run')
        factory.assert_not_called()

    def test_exclusive_output_does_not_dispatch_decisions(self):
        client, _, record = intake()
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(FileExistsError):
            run_confirmed_comparison(1, record, client, max_steps=3, max_model_calls_per_arm=4,
                                     env_factory=SyntheticStore, output_dir=tmp)
        self.assertEqual(len(client.records), 1)

    def test_replay_rejects_changed_original_and_initial_instruction(self):
        result, _ = self.compare()
        row = result['rows'][2]
        row['trajectory']['initial_result']['instruction'] += 'changed'
        with self.assertRaises(ValueError):
            verify_gate_replay(row)

    def test_cli_preflight_never_loads_runtime_or_credentials(self):
        from evaluation.confirmed_cli import main
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'config.json').write_text(json.dumps(asdict(fixture_client().config)), encoding='utf-8')
            with patch('evaluation.confirmed_cli.read_transient_key') as key, patch('builtins.print'):
                self.assertEqual(main(['--config', str(p / 'config.json'), '--runtime-dir', str(p / 'absent'),
                    '--split-dir', str(p / 'absent'), '--task-id', '1', '--output-dir', str(p / 'output'),
                    '--max-model-calls-per-arm', '4']), 0)
                key.assert_not_called()
                self.assertFalse((p / 'output').exists())


if __name__ == '__main__':
    unittest.main()
