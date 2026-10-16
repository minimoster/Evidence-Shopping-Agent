"""Offline integration: diagnostics affect B/C context, never gate permission."""
import json
import unittest
from evaluation.runner import RunConfig, run_task
from tests_evaluation.test_runner import FakeClient, FakeEnvironment


class DiagnosticRunnerTests(unittest.TestCase):
    def run_case(self, arm):
        env = FakeEnvironment()
        reset = env.reset
        def natural_reset(task_id):
            value = reset(task_id)
            value['instruction'] = '品类:耳机;预算约100元;颜色不要白色'
            return value
        env.reset = natural_reset
        client = FakeClient([('buy_now', {})])
        result = run_task(1, client, config=RunConfig(arm=arm, max_steps=1,
            max_model_calls=1), env_factory=lambda **kw: env)
        return result, env, client

    def test_only_intervention_arms_receive_diagnostics(self):
        for arm in 'ABC':
            row, _, client = self.run_case(arm)
            text = json.dumps(client.messages)
            self.assertEqual('predicate_diagnostics' in text, arm in 'BC')
            self.assertNotIn('DO_NOT_LEAK', text)
            self.assertFalse(row['query_analysis']['purchase_authorized'])
            self.assertFalse(row['parser_ready'])
            self.assertEqual(row['model_calls'], 1)

    def test_soft_or_negative_diagnostic_never_relaxes_gate(self):
        row, env, _ = self.run_case('C')
        self.assertEqual(env.actions, [])
        self.assertFalse(row['gate_events'][0]['decision']['allowed'])
        self.assertEqual(row['budget_steps'], 1)
        self.assertFalse(row['success'])
        predicates = [p for c in row['query_analysis']['clauses'] for p in c['predicates']]
        self.assertTrue(any(p['kind'] == 'negative' for p in predicates))
        self.assertTrue(any(p['strength'] == 'uncertain' for p in predicates))

    def test_b_still_does_not_intercept_purchase(self):
        row, env, _ = self.run_case('B')
        self.assertEqual(env.actions, ['click[Buy Now]'])
        self.assertEqual(row['gate_events'], [])
        self.assertTrue(row['wrong_purchase'])
