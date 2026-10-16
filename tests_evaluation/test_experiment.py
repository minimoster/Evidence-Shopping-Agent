"""Synthetic orchestration tests. No simulator/model/network service involved."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from evaluation.experiment import ExperimentManifest, complete_results, run_experiment, load_development_manifest
from evaluation.dev_split import task_ids_jsonl
from evaluation.runner import RunConfig, run_task, ShopAgentEnv
from evaluation.report import summarize
from tests_evaluation.test_runner import FakeClient, FakeEnvironment


def client_factory(**kwargs):
    return FakeClient([('buy_now', {})])

class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.plan = ExperimentManifest((1, 2, 3), RunConfig(max_steps=1))
    def run_plan(self, **kwargs):
        return run_experiment(self.plan, client_factory=client_factory, env_factory=FakeEnvironment, **kwargs)
    def test_rotation_and_fresh_clients_environments(self):
        seen = []
        envs = []
        def client(**kwargs):
            seen.append((kwargs['task_id'], kwargs['arm']))
            return client_factory()
        def env(**kwargs):
            obj = FakeEnvironment(); envs.append(obj); return obj
        rows = run_experiment(self.plan, client_factory=client, env_factory=env)
        self.assertEqual(seen, [(1,'A'),(1,'B'),(1,'C'),(2,'B'),(2,'C'),(2,'A'),(3,'C'),(3,'A'),(3,'B')])
        self.assertEqual(len(envs), 9)
        self.assertTrue(all(e.released for e in envs))
        self.assertEqual(len(rows), 9)
        self.assertTrue(summarize(rows, manifest=self.plan)['manifest_checked'])
    def test_missing_task_in_every_arm_keeps_full_denominator(self):
        def good_env(**kwargs):
            env = FakeEnvironment(); env.color = '黑色'; return env
        all_rows = run_experiment(self.plan, client_factory=client_factory, env_factory=good_env)
        rows = [r for r in all_rows if r['task_id'] != 2]
        report = summarize(rows, manifest=self.plan)
        self.assertEqual(len(report['missing_task_arms']), 3)
        self.assertEqual(report['expected_rows'], 9)
        for arm in 'ABC':
            self.assertEqual(report['arms'][arm]['tasks'], 3)
            self.assertEqual(report['arms'][arm]['missing_rows'], 1)
            self.assertEqual(report['arms'][arm]['all_task_success_rate'], 2 / 3)
            self.assertIsNone(report['arms'][arm]['wrong_purchase_all_task_rate'])
            self.assertIsNone(report['arms'][arm]['cost_usd'])
    def test_no_rows_still_reports_entire_expected_experiment(self):
        report = summarize([], manifest=self.plan)
        self.assertEqual(len(report['missing_task_arms']), 9)
        for arm in 'ABC':
            self.assertEqual(report['arms'][arm]['all_task_success_rate'], 0)
    def test_setup_error_is_retained_and_continues(self):
        def broken(**kwargs):
            if kwargs['task_id'] == 2:
                raise RuntimeError('DO_NOT_LEAK')
            return client_factory()
        rows = run_experiment(self.plan, client_factory=broken, env_factory=FakeEnvironment)
        self.assertEqual(len(rows), 9)
        self.assertNotIn('DO_NOT_LEAK', json.dumps(rows))
        report = summarize(rows, manifest=self.plan)
        for arm in 'ABC':
            self.assertEqual(report['arms'][arm]['error_rows'], 1)
            self.assertEqual(report['arms'][arm]['tasks'], 3)
    def test_manifest_roundtrip_and_tamper(self):
        self.assertEqual(ExperimentManifest.from_dict(self.plan.to_dict()), self.plan)
        tampered = self.plan.to_dict(); tampered['expected_rows'] = 6
        with self.assertRaises(ValueError): ExperimentManifest.from_dict(tampered)
    def test_reject_duplicate_unexpected_unbound_or_wrong_config(self):
        rows = self.run_plan()
        with self.assertRaises(ValueError): complete_results(rows + rows[:1], self.plan)
        for key, value in [('task_id', 999), ('experiment_sha256', 'bad'), ('config', {})]:
            damaged = copy.deepcopy(rows); damaged[0][key] = value
            with self.assertRaises(ValueError): complete_results(damaged, self.plan)
    def test_smoke_requires_injected_fixture_not_default_adapter(self):
        with patch.object(ShopAgentEnv, '_send', side_effect=AssertionError('network attempted')) as send:
            with self.assertRaises(ValueError): run_task(1, client_factory())
            with self.assertRaises(ValueError): run_task(1, client_factory(), env_factory=ShopAgentEnv)
            self.assertEqual(send.call_count, 0)
    def test_real_plan_fails_before_factories(self):
        plan = ExperimentManifest((1,), RunConfig(execution_kind='real_model_real_simulator'))
        def forbidden(**kwargs): raise AssertionError('must not invoke')
        with self.assertRaises(ValueError): run_experiment(plan, client_factory=forbidden, env_factory=forbidden)
    def test_exclusive_output_contains_manifest_before_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'run'
            self.run_plan(output_dir=path)
            manifest = ExperimentManifest.from_dict(json.loads((path/'manifest.json').read_text()))
            self.assertEqual(manifest.sha256, self.plan.sha256)
            self.assertEqual(len(list(path.glob('*.json'))), 10)
            with self.assertRaises(FileExistsError): self.run_plan(output_dir=path)
    def test_interruption_leaves_recoverable_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'run'
            def stop(**kwargs): raise KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):
                run_experiment(self.plan, client_factory=stop, env_factory=FakeEnvironment, output_dir=path)
            plan = ExperimentManifest.from_dict(json.loads((path/'manifest.json').read_text()))
            self.assertEqual(len(summarize([], manifest=plan)['missing_task_arms']), 9)
    def test_split_loader_verifies_bytes_and_count(self):
        ids = list(range(20)); data = task_ids_jsonl(ids)
        split = {'schema_version':'shopping-development-split-v1', 'split_role':'development_only',
            'contains_queries_or_labels':False,'task_ids':ids,'tasks_jsonl_sha256':hashlib.sha256(data).hexdigest(),
            'final_exclusion':{'task_count':200,'selected_overlap_count':0,'source_overlap_count':0}}
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); (p/'split.json').write_text(json.dumps(split)); (p/'tasks.jsonl').write_bytes(data)
            plan=load_development_manifest(p/'split.json',p/'tasks.jsonl')
            self.assertEqual(len(plan.schedule()),60)
            (p/'tasks.jsonl').write_bytes(data+b'\n')
            with self.assertRaises(ValueError): load_development_manifest(p/'split.json',p/'tasks.jsonl')
    def test_legacy_report_explicitly_not_manifest_checked(self):
        self.assertFalse(summarize(self.run_plan())['manifest_checked'])

if __name__ == '__main__': unittest.main()
