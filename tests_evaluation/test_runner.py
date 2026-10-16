"""MOCKED tests only. No model, simulator service, network or paid usage."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from evaluation.runner import RunConfig, run_task, write_trace
from evaluation.report import summarize
from evaluation.replay import verify_gate_replay

QUERY = '品类:耳机;预算:不超过100元;颜色:黑色'

class FakeEnvironment:
    def __init__(self, **kwargs):
        self.color = '白色'
        self.actions = []
        self.released = False
    def state(self):
        return {'observation_version': 'shopping-observation-v2', 'page_type': 'product_detail',
            'search_available': False, 'actions': ['Buy Now', '白色', '黑色'],
            'product': {'asin': '000000000101', 'category': '耳机', 'title': '原创测试',
                        'brand': '测试', 'key_attributes': [], 'price': '79'},
            'selected_price': '79', 'selected_options': {'颜色': self.color},
            'available_options': {'颜色': ['白色', '黑色']}}
    def reset(self, task_id):
        return {'instruction': QUERY, 'goal_options': {'secret': 'hidden'},
                '_trace_target': {'asin': 'DO_NOT_LEAK'}, 'observation_state': self.state()}
    def step(self, action):
        self.actions.append(action)
        if action == 'click[黑色]':
            self.color = '黑色'
        done = action == 'click[Buy Now]'
        good = self.color == '黑色'
        state = self.state()
        if done:
            state = {'observation_version': 'shopping-observation-v2', 'page_type': 'terminal',
                     'search_available': False, 'actions': []}
        return {'instruction': 'hidden result text DO_NOT_LEAK', 'observation_state': state,
            'done': done, 'over': done, 'reward': int(good),
            'reward_detail': {'reward_version': 'shopsimulator-reward-v3', 'reward_valid': True,
                'reward_type': 'gold_purchase' if good else 'wrong_purchase',
                'termination_reason': 'gold_purchase' if good else 'wrong_purchase',
                'purchase_success': good}}
    def release(self):
        self.released = True

class FakeClient:
    execution_kind = 'mocked_smoke'
    def __init__(self, actions):
        self.actions = iter(actions)
        self.messages = []
    def complete(self, messages, tools):
        self.messages.append(copy.deepcopy(messages))
        name, args = next(self.actions)
        return {'role': 'assistant', 'content': None, 'tool_calls': [{'id': str(len(self.messages)),
            'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}

class RunnerTests(unittest.TestCase):
    def run_arm(self, arm, actions, **kwargs):
        env = FakeEnvironment()
        client = FakeClient(actions)
        row = run_task(1, client, config=RunConfig(arm=arm, **kwargs), env_factory=lambda **k: env)
        self.assertTrue(env.released)
        self.assertNotIn('DO_NOT_LEAK', json.dumps(client.messages))
        self.assertNotIn('DO_NOT_LEAK', json.dumps(row))
        return row, env, client
    def test_gate_recovers_with_same_budget(self):
        row, env, client = self.run_arm('C', [('buy_now', {}), ('select_option', {'value': '黑色'}), ('buy_now', {})])
        self.assertTrue(row['success'])
        self.assertEqual(row['executed_steps'], 2)
        self.assertEqual(row['budget_steps'], 3)
        self.assertEqual(row['model_calls'], 3)
        self.assertEqual(len(row['gate_events']), 2)
        self.assertEqual(verify_gate_replay(row)['gate_decisions_checked'], 2)
        damaged = copy.deepcopy(row)
        damaged['gate_events'][0]['decision']['allowed'] = True
        with self.assertRaises(ValueError):
            verify_gate_replay(damaged)
        self.assertFalse(row['gate_events'][0]['executed'])
        self.assertIn('Evidence gate rejected', json.dumps(client.messages, ensure_ascii=False))
    def test_baseline_wrong_purchase_is_counted(self):
        row, env, client = self.run_arm('A', [('buy_now', {})])
        self.assertFalse(row['success'])
        self.assertTrue(row['wrong_purchase'])
        self.assertNotIn('Query-only compilation', json.dumps(client.messages))
    def test_b_compiles_without_enforcing_gate(self):
        row, _, client = self.run_arm('B', [('buy_now', {})])
        self.assertEqual(row['gate_events'], [])
        self.assertTrue(row['wrong_purchase'])
        self.assertIn('Query-only compilation', json.dumps(client.messages))
    def test_rejection_does_not_reset_budget(self):
        row, env, _ = self.run_arm('C', [('buy_now', {})] * 8, max_steps=2)
        self.assertEqual(row['budget_steps'], 2)
        self.assertEqual(env.actions, [])
        self.assertEqual(row['trajectory']['status'], 'max_steps')
    def test_invalid_actions_consume_model_budget(self):
        row, _, _ = self.run_arm('A', [('open_product', {'asin': '99999999'})] * 5, max_model_calls=2)
        self.assertEqual(row['model_calls'], 2)
        self.assertEqual(row['trajectory']['status'], 'model_call_budget')
    def test_real_execution_is_not_mislabeled_or_enabled(self):
        client = FakeClient([])
        with self.assertRaises(ValueError):
            run_task(1, client, config=RunConfig(execution_kind='real_model_real_simulator'))
        client.execution_kind = 'real_model_real_simulator'
        with self.assertRaises(ValueError):
            run_task(1, client, config=RunConfig(execution_kind=client.execution_kind))
    def test_report_denominators_and_pairs(self):
        a, _, _ = self.run_arm('A', [('buy_now', {})])
        c, _, _ = self.run_arm('C', [('buy_now', {})], max_steps=1)
        report = summarize([a, c])
        self.assertEqual(report['arms']['A']['wrong_purchase_all_task_rate'], 1)
        self.assertIsNone(report['arms']['C']['wrong_purchase_conditioned_rate'])
        self.assertIsNone(report['arms']['C']['gate_false_rejection_rate'])
        self.assertIsNone(report['arms']['A']['cost_usd'])
        self.assertTrue(report['paired']['A_vs_C']['complete_pairing'])
        self.assertFalse(report['paired']['A_vs_C']['comparable_configurations'])
        with self.assertRaises(ValueError):
            summarize([a, a])
    def test_trace_exclusive_and_no_hidden_payload(self):
        row, _, _ = self.run_arm('A', [('buy_now', {})])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'trace.json'
            self.assertEqual(len(write_trace(p, row)), 64)
            with self.assertRaises(FileExistsError):
                write_trace(p, row)
    def test_step_exception_text_not_persisted(self):
        env = FakeEnvironment()
        def fail(action):
            raise RuntimeError('DO_NOT_LEAK private response')
        env.step = fail
        row = run_task(1, FakeClient([('buy_now', {})]), env_factory=lambda **k: env)
        self.assertNotIn('DO_NOT_LEAK', json.dumps(row))
        self.assertEqual(row['trajectory']['steps'][0]['error'], {'type': 'RuntimeError'})
    def test_release_failure_does_not_make_gold_purchase_wrong(self):
        env = FakeEnvironment()
        env.color = '黑色'
        def fail_release():
            raise RuntimeError('DO_NOT_LEAK')
        env.release = fail_release
        row = run_task(1, FakeClient([('buy_now', {})]), env_factory=lambda **k: env)
        self.assertFalse(row['success'])
        self.assertFalse(row['wrong_purchase'])
        self.assertNotIn('DO_NOT_LEAK', json.dumps(row))
    def test_alternative_purchase_is_not_wrong(self):
        env = FakeEnvironment()
        original = env.step
        def alternative(action):
            result = original(action)
            result['reward_detail']['reward_type'] = 'valid_alternative_purchase'
            return result
        env.step = alternative
        row = run_task(1, FakeClient([('buy_now', {})]), env_factory=lambda **k: env)
        self.assertFalse(row['success'])
        self.assertFalse(row['wrong_purchase'])
    def test_release_failure_survives_budget_exhaustion(self):
        env = FakeEnvironment()
        env.release = lambda: (_ for _ in ()).throw(RuntimeError('release failed'))
        row = run_task(1, FakeClient([('buy_now', {})]), config=RunConfig(arm='C', max_model_calls=1), env_factory=lambda **k: env)
        self.assertEqual(row['trajectory']['status'], 'environment_release_failed')
        self.assertIsNotNone(row['trajectory']['release_error'])
    def test_failed_dispatch_is_not_confirmed_execution(self):
        env = FakeEnvironment()
        env.color = '黑色'
        env.step = lambda action: (_ for _ in ()).throw(RuntimeError('failed'))
        row = run_task(1, FakeClient([('buy_now', {})]), config=RunConfig(arm='C'), env_factory=lambda **k: env)
        self.assertEqual(row['executed_steps'], 0)
        self.assertEqual(row['dispatched_steps'], 1)
        self.assertIsNone(row['gate_events'][0]['executed'])
        self.assertTrue(row['purchase_outcome_unknown'])
        self.assertIsNone(summarize([row])['arms']['C']['wrong_purchase_all_task_rate'])
    def test_replay_binds_tool_payload(self):
        row, _, _ = self.run_arm('C', [('buy_now', {})], max_steps=1)
        row['gate_events'][0]['action'] = 'search[not buy]'
        with self.assertRaises(ValueError):
            verify_gate_replay(row)
    def test_replay_denial_cannot_be_uncertain_dispatch(self):
        row, _, _ = self.run_arm('C', [('buy_now', {})], max_steps=1)
        row['gate_events'][0]['executed'] = None
        row['trajectory']['steps'][0]['error'] = {'type': 'TimeoutError'}
        with self.assertRaises(ValueError):
            verify_gate_replay(row)
    def test_hidden_public_state_rejected(self):
        env = FakeEnvironment()
        original = env.state
        env.state = lambda: dict(original(), goal={'answer': 'DO_NOT_LEAK'})
        row = run_task(1, FakeClient([]), env_factory=lambda **k: env)
        self.assertEqual(row['model_calls'], 0)
        self.assertEqual(row['trajectory']['status'], 'error')
        self.assertNotIn('DO_NOT_LEAK', json.dumps(row))
        self.assertTrue(env.released)

if __name__ == '__main__':
    unittest.main()
