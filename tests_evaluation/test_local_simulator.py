"""Local adapter unit tests; real reset checks are explicitly opt-in and labeled.

EVIDENCE_SHOPPING_REAL_SIMULATOR_RUNTIME=/existing/runtime python -m unittest \
    tests_evaluation.test_local_simulator.RealSimulatorResetTests -v

Only the opt-in class loads real data, and it performs reset/release only.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from project_paths import ROOT, upstream_path
from evaluation.local_simulator import (
    LocalSimulatorRuntime, SimulatorValidationError, validate_resets,
    verify_development_split,
)

sys.path.insert(0, str(upstream_path() / "src"))
from shopping_grpo.environment.client import ShopAgentEnv, ShopEnvironmentStateError


class MockLeasePool:
    def __init__(self, count):
        self.free = {0}
    def acquire(self):
        return self.free.pop() if self.free else None
    def release(self, value):
        released = value not in self.free
        self.free.add(value)
        return released
    def free_slots(self):
        return frozenset(self.free)


class MockTextEnv:
    def __init__(self, **kwargs):
        self.closed = False
        self.search_closed = False
        self.server = SimpleNamespace(environment_version='shopsimulator-environment-v2.1',
            search_engine=SimpleNamespace(close=self.close_search))
    def close(self):
        self.closed = True
    def close_search(self):
        self.search_closed = True


def mock_handle(env, slot, action, idx=None, response=None, include_trace_target=False):
    state = {'observation_version': 'shopping-observation-v2',
        'page_type': 'search_home' if action == 'reset' else 'terminal',
        'actions': [], 'search_available': action == 'reset'}
    common = {'observation_state': state, 'env_idx': slot, 'idx': idx,
        'goal': {'asin': 'SECRET'}, 'goal_options': {'color': 'SECRET'},
        'instruction_simple': 'SECRET', 'user_persona': {'private': 'SECRET'}}
    if action == 'reset':
        return {**common, 'instruction': '品类:耳机;预算:不超过100元',
            'environment_version': 'shopsimulator-environment-v2.1'}
    return {**common, 'instruction': 'SECRET TERMINAL LABEL', 'done': True,
        'over': True, 'reward': -0.35,
        'reward_detail': {'reward_version': 'shopsimulator-reward-v3', 'reward_valid': True,
                          'reward_type': 'early_abstain'}}


class MockAdapterLifecycleTests(unittest.TestCase):
    """MOCKED simulator only; uses the real, unchanged upstream client class."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patches = [
            patch('evaluation.local_simulator.verify_development_split', return_value=([302], {'tasks_jsonl_sha256': 'fake'})),
            patch('evaluation.local_simulator.verify_runtime_assets', return_value={'environment_version': 'shopsimulator-environment-v2.1'}),
            patch('evaluation.local_simulator._load_runtime_types', return_value=(MockTextEnv, MockLeasePool, ShopAgentEnv,
                mock_handle, lambda state: 'PUBLIC RENDER')),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.runtime = LocalSimulatorRuntime(self.tmp.name)
        self.addCleanup(self.runtime.close)

    def test_actual_upstream_client_and_lifecycle(self):
        client = self.runtime.env_factory()
        self.assertIsInstance(client, ShopAgentEnv)
        self.assertTrue(self.runtime.verified)
        with self.assertRaises(ShopEnvironmentStateError):
            client.step('finish')
        try:
            result = client.reset(302)
            self.assertEqual(self.runtime.active_leases, 1)
            self.assertNotIn('SECRET', json.dumps(result))
            with self.assertRaises(ShopEnvironmentStateError):
                client.reset(302)
            result = client.step('finish')
            self.assertEqual(result['instruction'], 'PUBLIC RENDER')
            self.assertEqual(result['reward_detail']['reward_type'], 'early_abstain')
            self.assertNotIn('SECRET', json.dumps(result))
            self.assertEqual(self.runtime.active_leases, 1)
            with self.assertRaises(ShopEnvironmentStateError):
                client.step('finish')
        finally:
            client.release()
        self.assertEqual(self.runtime.active_leases, 0)
        self.assertIsNone(client.release())

    def test_reject_non_development_id_and_hidden_targets_before_lease(self):
        client = self.runtime.env_factory()
        with self.assertRaisesRegex(ValueError, 'development'):
            client.reset(99999)
        client.include_trace_target = True
        with self.assertRaisesRegex(ValueError, 'hidden'):
            client.reset(302)
        self.assertEqual(self.runtime.active_leases, 0)

    def test_cannot_close_or_steal_active_lease(self):
        first, second = self.runtime.env_factory(), self.runtime.env_factory()
        try:
            first.reset(302)
            with self.assertRaisesRegex(RuntimeError, 'already leased'):
                second.reset(302)
            with self.assertRaisesRegex(RuntimeError, 'release'):
                self.runtime.close()
        finally:
            first.release()
        second.reset(302)
        second.release()
        self.runtime.close()
        self.assertFalse(self.runtime.verified)
        self.assertTrue(self.runtime._env.closed)
        self.assertTrue(self.runtime._env.search_closed)
        with self.assertRaisesRegex(RuntimeError, 'closed'):
            self.runtime.env_factory()

    def test_failed_reset_releases_pool(self):
        self.runtime._handle = lambda *args, **kwargs: (_ for _ in ()).throw(ValueError('failed'))
        with self.assertRaisesRegex(ValueError, 'failed'):
            self.runtime.env_factory().reset(302)
        self.assertEqual(self.runtime.active_leases, 0)

    def test_reset_validation_never_persists_query_or_uses_step(self):
        summary = validate_resets(self.runtime)
        self.assertEqual(summary['simulator_steps'], 0)
        self.assertEqual(summary['successful_releases'], 1)
        self.assertEqual(summary['parser_ready_count'], 1)
        self.assertNotIn('耳机', json.dumps(summary, ensure_ascii=False))
        self.assertFalse(summary['query_text_persisted'])


@unittest.skipUnless((ROOT / 'runtime/dev20/manifest.json').exists(), 'ignored development split not present')
class LocalProvenanceTests(unittest.TestCase):
    """IDs-only local files; no simulator, model, data corpus or network."""
    def test_pinned_development_split(self):
        ids, metadata = verify_development_split()
        self.assertEqual(len(ids), 20)
        self.assertEqual(ids, metadata['task_ids'])
    def test_changed_ids_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            for name in ('tasks.jsonl', 'manifest.json'):
                (destination / name).write_bytes((ROOT / 'runtime/dev20' / name).read_bytes())
            rows = (destination / 'tasks.jsonl').read_text().splitlines()
            rows[0] = '{"task_id":1}'
            (destination / 'tasks.jsonl').write_text('\n'.join(rows) + '\n')
            with self.assertRaises(SimulatorValidationError):
                verify_development_split(destination)


    def test_rehashed_replacement_split_is_not_authorized(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            ids, metadata = verify_development_split()
            # Change ordering-independent selection and recompute its own hash;
            # self-consistent metadata must not expand the approved allowlist.
            ids[0] = 0
            data = ''.join(json.dumps({'task_id': value}, separators=(',', ':')) + '\n' for value in ids).encode()
            metadata['task_ids'] = ids
            metadata['tasks_jsonl_sha256'] = hashlib.sha256(data).hexdigest()
            (destination / 'tasks.jsonl').write_bytes(data)
            (destination / 'manifest.json').write_text(json.dumps(metadata))
            with self.assertRaises(SimulatorValidationError):
                verify_development_split(destination)


@unittest.skipUnless(os.environ.get('EVIDENCE_SHOPPING_REAL_SIMULATOR_RUNTIME'),
    'REAL simulator validation is opt-in, not a mocked test')
class RealSimulatorResetTests(unittest.TestCase):
    """REAL pinned simulator; only approved dev20 resets and releases, no steps."""
    def test_twenty_real_resets_and_releases(self):
        from offline_checks import DENIED_EVENTS, deny_external_actions
        sys.addaudithook(deny_external_actions)
        before = len(DENIED_EVENTS)
        with LocalSimulatorRuntime(os.environ['EVIDENCE_SHOPPING_REAL_SIMULATOR_RUNTIME']) as runtime:
            summary = validate_resets(runtime)
            self.assertTrue(runtime.verified)
            self.assertEqual(summary['task_count'], 20)
            self.assertEqual(summary['successful_resets'], 20)
            self.assertEqual(summary['successful_releases'], 20)
            self.assertEqual(runtime.active_leases, 0)
            self.assertEqual(summary['model_calls'], 0)
            self.assertEqual(summary['simulator_steps'], 0)
            self.assertFalse(summary['final200_queries_or_labels_examined'])
        self.assertEqual(len(DENIED_EVENTS), before)


if __name__ == '__main__':
    unittest.main()
