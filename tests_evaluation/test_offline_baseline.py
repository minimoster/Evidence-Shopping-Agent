"""Original offline A/B/C fixture integration; no service, model, or GPU."""
import copy
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from evaluation.experiment import run_experiment
from evaluation.failure_analysis import analyze_failures
from evaluation.offline_baseline import (
    FIXTURES, RESULTS_ROOT, WARNING, ScriptedFixtureActor, ScriptedFixtureEnvironment,
    _client_factory, _PRIVATE_MARKER, build_public_outputs, main, make_manifest, run_baseline,
    _require_bundled_upstream, _source_fingerprints,
)
from evaluation.runner import ShopAgentEnv


def run_fixture_rows(**budgets):
    manifest = make_manifest(**budgets)
    return manifest, run_experiment(manifest, client_factory=_client_factory,
                                    env_factory=ScriptedFixtureEnvironment)


class OfflineBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.rows = run_fixture_rows()
        cls.keyed = {(r['task_id'], r['arm']): r for r in cls.rows}

    def test_all_fifteen_slots_same_finite_configuration(self):
        self.assertEqual(len(FIXTURES), 5)
        self.assertEqual(len(self.rows), 15)
        self.assertEqual([(r['task_id'], r['arm']) for r in self.rows], self.manifest.schedule())
        for row in self.rows:
            self.assertEqual(row['execution_kind'], 'mocked_smoke')
            self.assertEqual(row['config']['max_steps'], 3)
            self.assertEqual(row['config']['max_model_calls'], 3)
            self.assertLessEqual(row['budget_steps'], 3)
            self.assertLessEqual(row['model_calls'], 3)
        report, _, _ = build_public_outputs(self.rows, self.manifest)
        self.assertTrue(report['manifest_checked'])
        self.assertEqual(report['expected_rows'], 15)
        self.assertEqual(report['missing_task_arms'], [])
        self.assertTrue(all(p['complete_pairing'] and p['comparable_configurations']
                            for p in report['paired'].values()))

    def test_provenance_covers_pinned_upstream_and_local_dependencies(self):
        fingerprints = _source_fingerprints()
        for path in ('project_paths.py', 'shopping_demo/core.py',
                     'evaluation/query_analysis.py', 'prototype/purchase_guard.py',
                     'upstream_reference/src/shopping_grpo/evaluation/metrics.py',
                     'upstream_reference/src/shopping_grpo/environment/actions.py'):
            self.assertEqual(len(fingerprints[path]), 64)
        _, _, provenance = build_public_outputs(self.rows, self.manifest)
        self.assertTrue(provenance['upstream_python_manifest_verified'])
        self.assertIn('bundled_snapshot_only', provenance['upstream_selection'])

    def test_alternate_upstream_rejected_before_import_or_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / 'src/shopping_grpo'
            package.mkdir(parents=True)
            (package / '__init__.py').write_text("raise AssertionError('ALTERNATE_SOURCE_EXECUTED')\n")
            environment = dict(os.environ, EVIDENCE_SHOPPING_UPSTREAM=tmp)
            completed = subprocess.run([sys.executable, '-m', 'evaluation.offline_baseline'],
                cwd=RESULTS_ROOT.parent, env=environment, text=True, capture_output=True, timeout=10)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn('require the bundled upstream snapshot', completed.stderr)
            self.assertNotIn('ALTERNATE_SOURCE_EXECUTED', completed.stderr)
            with patch.dict(os.environ, {'EVIDENCE_SHOPPING_UPSTREAM': tmp}):
                with self.assertRaises(RuntimeError):
                    run_baseline(RESULTS_ROOT / 'must-not-create-alternate-source')
            self.assertFalse((RESULTS_ROOT / 'must-not-create-alternate-source').exists())

    def test_import_cached_alternate_module_rejected(self):
        from types import SimpleNamespace
        with patch.dict(sys.modules, {'shopping_grpo.injected': SimpleNamespace(__file__='/tmp/alternate.py')}):
            with self.assertRaises(RuntimeError):
                _require_bundled_upstream()

    def test_changed_upstream_hash_rejected_without_editing_source(self):
        original = Path.read_bytes
        def altered(path):
            content = original(path)
            if path.as_posix().endswith('shopping_grpo/evaluation/rollout.py'):
                return content + b'\n# altered fixture\n'
            return content
        with patch.object(Path, 'read_bytes', altered):
            with self.assertRaises(RuntimeError):
                _source_fingerprints()

    def test_exact_scripted_outcomes_are_not_real_performance(self):
        report, failure, provenance = build_public_outputs(self.rows, self.manifest)
        for arm in ('A', 'B'):
            self.assertEqual(report['arms'][arm]['successes'], 3)
            self.assertEqual(report['arms'][arm]['wrong_purchases_known'], 2)
            self.assertEqual(report['arms'][arm]['scripted_actor_calls'], 5)
        self.assertEqual(report['arms']['C']['successes'], 2)
        self.assertEqual(report['arms']['C']['wrong_purchases_known'], 0)
        self.assertEqual(report['arms']['C']['gate_rejections'], 10)
        self.assertEqual(report['arms']['C']['scripted_actor_calls'], 13)
        self.assertEqual(report['warning'], WARNING)
        self.assertFalse(report['performance_claim_permitted'])
        self.assertEqual(report['external_model_requests'], 0)
        self.assertEqual(report['real_simulator_tasks'], 0)
        self.assertFalse(provenance['real_performance_evidence'])
        self.assertIsNone(failure['gate_false_rejection_rate'])
        for arm in report['arms'].values():
            self.assertIsNone(arm['cost_usd'])
            self.assertIsNone(arm['input_tokens'])
            self.assertIsNone(arm['gate_false_rejection_rate'])

    def test_each_original_fixture_has_expected_gate_behavior(self):
        for arm in 'ABC':
            self.assertTrue(self.keyed[910001, arm]['success'])
        self.assertTrue(self.keyed[910002, 'A']['wrong_purchase'])
        self.assertFalse(self.keyed[910002, 'C']['purchased'])
        price = self.keyed[910003, 'C']
        self.assertIn('price_unknown', price['gate_events'][0]['decision']['reasons'])
        self.assertFalse(price['purchased'])
        self.assertTrue(self.keyed[910003, 'A']['success'])
        prose = self.keyed[910004, 'C']
        self.assertFalse(prose['parser_ready'])
        self.assertFalse(prose['purchased'])
        self.assertTrue(any(r.startswith('query:') for r in prose['gate_events'][0]['decision']['reasons']))

    def test_recovery_spends_rejected_step_and_call_without_replacement(self):
        row = self.keyed[910005, 'C']
        self.assertTrue(row['success'])
        self.assertEqual(row['budget_steps'], 3)
        self.assertEqual(row['model_calls'], 3)
        self.assertEqual(row['executed_steps'], 2)
        self.assertEqual([g['executed'] for g in row['gate_events']], [False, True])
        for budget in ({'max_steps': 2}, {'max_model_calls': 2}):
            _, rows = run_fixture_rows(**budget)
            limited = next(r for r in rows if r['task_id'] == 910005 and r['arm'] == 'C')
            self.assertFalse(limited['success'])
            self.assertEqual(limited['model_calls'], 2)
            self.assertEqual(limited['budget_steps'], 2)

    def test_actor_policy_is_arm_blind_and_score_blind(self):
        sequences = []
        for arm in 'ABC':
            actor = _client_factory(task_id=910005, arm=arm)
            sequences.append([actor.complete([], [])['tool_calls'][0]['function'] for _ in range(3)])
        self.assertEqual(sequences[0], sequences[1])
        self.assertEqual(sequences[1], sequences[2])
        self.assertEqual([s['name'] for s in sequences[0]], ['buy_now', 'select_option', 'buy_now'])

    def test_no_network_or_default_adapter_or_credential_route(self):
        with ExitStack() as stack:
            for target in ('socket.socket', 'socket.create_connection', 'urllib.request.urlopen',
                           'getpass.getpass'):
                stack.enter_context(patch(target, side_effect=AssertionError('forbidden external route')))
            send = stack.enter_context(patch.object(ShopAgentEnv, '_send',
                                       side_effect=AssertionError('real adapter touched')))
            _, rows = run_fixture_rows()
            self.assertEqual(len(rows), 15)
            self.assertTrue(all(r['trajectory']['status'] in {'done', 'max_steps'} for r in rows))
            send.assert_not_called()

    def test_raw_scorer_payload_never_enters_actor_or_trace(self):
        observed = []
        original = ScriptedFixtureActor.complete
        def capture(actor, messages, tools):
            observed.append(copy.deepcopy(messages))
            return original(actor, messages, tools)
        with patch.object(ScriptedFixtureActor, 'complete', capture):
            _, rows = run_fixture_rows()
        for payload in (rows, observed):
            serialized = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn(_PRIVATE_MARKER, serialized)
            self.assertNotIn('reward_detail', serialized)
            self.assertNotIn('goal_options', serialized)
        self.assertIn(FIXTURES[0].query, json.dumps(rows, ensure_ascii=False))

    def test_share_safe_projection_has_no_queries_product_or_raw_gate_payload(self):
        rows = copy.deepcopy(self.rows)
        # Future detailed NLU additions must remain private too.
        for row in rows:
            row['query_analysis'] = {'query': _PRIVATE_MARKER,
                                     'predicates': [{'span': {'text': _PRIVATE_MARKER}}]}
        public = build_public_outputs(rows, self.manifest)
        serialized = json.dumps(public, ensure_ascii=False)
        for forbidden in (FIXTURES[0].query, FIXTURES[3].query, _PRIVATE_MARKER,
                          '000000910001', '原创离线样例', '黑色',
                          'observation_state', 'reward_detail', 'query_digest'):
            self.assertNotIn(forbidden, serialized)
        for output in public:
            self.assertFalse(output['contains_queries_observations_or_private_labels'])

    def test_replay_all_five_C_traces_and_reject_tampering(self):
        _, _, provenance = build_public_outputs(self.rows, self.manifest)
        self.assertEqual(provenance['gate_replay_expected_rows'], 5)
        self.assertEqual(provenance['gate_replay_checked_rows'], 5)
        self.assertEqual(provenance['gate_replay_decisions_checked'], 12)
        self.assertTrue(all(r['consistent'] and not r['authenticity_verified']
                            for r in provenance['gate_replay']))
        damaged = copy.deepcopy(self.rows)
        row = next(r for r in damaged if r['arm'] == 'C')
        row['gate_events'][0]['decision']['allowed'] = False
        with self.assertRaises(ValueError):
            build_public_outputs(damaged, self.manifest)

    def test_missing_rows_preserve_denominator_and_unknowns(self):
        rows = [r for r in self.rows if r['task_id'] != 910003]
        report, failure, provenance = build_public_outputs(rows, self.manifest)
        self.assertEqual(report['expected_rows'], 15)
        self.assertEqual(len(report['missing_task_arms']), 3)
        self.assertEqual(failure['analyzed_rows'], 15)
        self.assertEqual(failure['missing_rows'], 3)
        self.assertEqual(provenance['gate_replay_checked_rows'], 4)
        for case in failure['cases']:
            if case['task_id'] == 910003:
                self.assertIsNone(case['parser_ready'])
                self.assertIn('missing_or_unattempted_slot', case['tags'])
                self.assertNotIn('parser_not_ready', case['tags'])
        for arm in report['arms'].values():
            self.assertEqual(arm['tasks'], 5)
            self.assertIsNone(arm['wrong_purchase_all_task_rate'])

    def test_failure_tags_do_not_echo_unknown_reason_or_exception_payload(self):
        rows = copy.deepcopy(self.rows)
        row = next(r for r in rows if r['arm'] == 'C' and r['gate_events'])
        row['trajectory']['status'] = _PRIVATE_MARKER
        row['gate_events'][0]['executed'] = False
        row['gate_events'][0]['decision']['reasons'] = [_PRIVATE_MARKER, 'query:' + _PRIVATE_MARKER]
        output = analyze_failures(rows, manifest=self.manifest)
        self.assertNotIn(_PRIVATE_MARKER, json.dumps(output))
        self.assertIn('other_guard_requirement', output['tag_counts'])

    def test_public_semantic_outputs_repeat_exactly(self):
        manifest, rows = run_fixture_rows()
        self.assertEqual(manifest.sha256, self.manifest.sha256)
        self.assertEqual(build_public_outputs(rows, manifest),
                         build_public_outputs(self.rows, self.manifest))

    def test_output_is_exclusive_private_and_only_under_ignored_results(self):
        RESULTS_ROOT.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=RESULTS_ROOT) as tmp:
            directory = Path(tmp) / 'run'
            report = run_baseline(directory)
            self.assertEqual(report['expected_rows'], 15)
            self.assertEqual(len(list((directory / 'private').glob('*.json'))), 16)
            self.assertEqual(len(list((directory / 'public').glob('*.json'))), 3)
            for path in directory.rglob('*'):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)
            with self.assertRaises(FileExistsError):
                run_baseline(directory)
            outside = Path(tmp).parent.parent / 'must-not-create-baseline-output'
            with self.assertRaises(ValueError):
                run_baseline(outside)
            self.assertFalse(outside.exists())
            with tempfile.TemporaryDirectory() as other:
                (Path(tmp) / 'escape').symlink_to(other, target_is_directory=True)
                with self.assertRaises(ValueError):
                    run_baseline(Path(tmp) / 'escape' / 'run')

    def test_budget_bounds_and_cli_summary(self):
        for kwargs in ({'max_steps': 0}, {'max_steps': 31}, {'max_steps': True},
                       {'max_model_calls': 31}, {'seed': 'not-an-integer'}):
            with self.assertRaises(ValueError):
                make_manifest(**kwargs)
        RESULTS_ROOT.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=RESULTS_ROOT) as tmp:
            output, error = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(error):
                self.assertEqual(main(['--output-dir', str(Path(tmp) / 'cli')]), 0)
                self.assertEqual(main(['--output-dir', str(Path(tmp) / 'cli')]), 2)
            self.assertEqual(json.loads(output.getvalue())['status'], 'mocked_smoke_complete')
            self.assertEqual(json.loads(error.getvalue())['error_type'], 'FileExistsError')
            self.assertNotIn(FIXTURES[0].query, output.getvalue() + error.getvalue())

    def test_cli_errors_remain_in_denominator_and_return_nonzero(self):
        RESULTS_ROOT.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=RESULTS_ROOT) as tmp:
            output = io.StringIO()
            with patch.object(ScriptedFixtureEnvironment, 'reset', side_effect=RuntimeError(_PRIVATE_MARKER)):
                with redirect_stdout(output):
                    self.assertEqual(main(['--output-dir', str(Path(tmp) / 'errors')]), 1)
            status = json.loads(output.getvalue())
            self.assertEqual(status['status'], 'mocked_smoke_with_errors')
            report = json.loads((Path(tmp) / 'errors' / 'public' / 'summary.json').read_text())
            self.assertEqual(report['expected_rows'], 15)
            self.assertTrue(all(arm['tasks'] == 5 and arm['error_rows'] == 5
                                for arm in report['arms'].values()))
            self.assertNotIn(_PRIVATE_MARKER, json.dumps(report))


if __name__ == '__main__':
    unittest.main()
