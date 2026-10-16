"""Run a bounded original scripted A/B/C fixture comparison, entirely offline.

Usage: python -m evaluation.offline_baseline --output-dir results/offline-baseline-v1

No model, API credential, network, GPU, training data, real simulator service, or
marketplace is used. The existing experiment, runner, pinned upstream collector,
purchase guard, report, and gate replay are exercised rather than reimplemented.
This is mocked_smoke integration evidence, never a real success improvement.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import sys

from project_paths import ROOT, UPSTREAM_COMMIT, upstream_path


def _require_bundled_upstream():
    """Do not attribute an alternate/import-cached upstream to the pinned copy."""
    bundled = (ROOT / 'upstream_reference').resolve()
    if upstream_path().resolve() != bundled:
        raise RuntimeError('offline fixtures require the bundled upstream snapshot')
    source = bundled / 'src'
    for name, module in tuple(sys.modules.items()):
        if name == 'shopping_grpo' or name.startswith('shopping_grpo.'):
            filename = getattr(module, '__file__', None)
            if filename is not None and not Path(filename).resolve().is_relative_to(source):
                raise RuntimeError('offline fixtures reject alternate loaded upstream modules')


# Check before importing runner/experiment, which select and load upstream code.
_require_bundled_upstream()

from .experiment import ExperimentManifest, run_experiment
from .failure_analysis import analyze_failures
from .replay import verify_gate_replay
from .report import summarize
from .runner import RunConfig, write_trace


RESULTS_ROOT = ROOT / 'results'
SUITE_VERSION = 'original-scripted-shopping-fixtures-v1'
WARNING = ('MOCKED_SMOKE / SCRIPTED FIXTURE ONLY. No real model or simulator service '
           'was run. These numbers do not estimate or demonstrate real-model success improvement.')
_QUERY = '品类:耳机;预算:不超过100元;颜色:黑色'
_PRIVATE_MARKER = 'SYNTHETIC_PRIVATE_SCORER_VALUE_DO_NOT_EXPORT'


@dataclass(frozen=True)
class Fixture:
    task_id: int
    case: str
    query: str
    initial_color: str = '黑色'
    price_visible: bool = True
    recover_variant: bool = False


FIXTURES = (
    Fixture(910001, 'correct_evidence', _QUERY),
    Fixture(910002, 'wrong_variant', _QUERY, initial_color='白色'),
    Fixture(910003, 'missing_current_price', _QUERY, price_visible=False),
    Fixture(910004, 'unsupported_natural_query', '请找一副通勤用的黑色耳机，最多花一百元。'),
    Fixture(910005, 'recover_after_gate_rejection', _QUERY,
            initial_color='白色', recover_variant=True),
)
_BY_ID = {fixture.task_id: fixture for fixture in FIXTURES}


class ScriptedFixtureActor:
    """One fixed policy per fixture, identical across arms and blind to scores.

    The first action is always buy. Only the designated recovery script selects
    black on call 2, then retries buy. It does not inspect compilation, arm names,
    reward, hidden target data, or scores. It repeats buy until a finite budget
    ends the attempt; it cannot retry/reset the collector or grant extra budget.
    """
    execution_kind = 'mocked_smoke'

    def __init__(self, *, recover_variant=False):
        self.recover_variant = recover_variant
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        name, arguments = ('select_option', {'value': '黑色'}) if (
            self.recover_variant and self.calls == 2) else ('buy_now', {})
        return {'role': 'assistant', 'content': None, 'tool_calls': [{
            'id': f'scripted-{self.calls}', 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)},
        }]}


class ScriptedFixtureEnvironment:
    """Original tiny fixture, NOT ShopSimulator or a marketplace adapter.

    Its private scorer intentionally knows a handcrafted correct black variant
    at 79 CNY even when the public price is absent or prose is unsupported. That
    illustrates a fail-closed evidence trade-off, not adjudication of real tasks.
    """
    def __init__(self, **kwargs):
        self.fixture = None
        self.color = None
        self.released = False

    def state(self):
        state = {
            'observation_version': 'shopping-observation-v2',
            'page_type': 'product_detail', 'search_available': False,
            'actions': ['Buy Now', '白色', '黑色'],
            'product': {'asin': '000000910001', 'category': '耳机',
                        'title': '原创离线样例', 'brand': '样例品牌',
                        'key_attributes': [], 'price': '79'},
            'selected_options': {'颜色': self.color},
            'available_options': {'颜色': ['白色', '黑色']},
        }
        if self.fixture.price_visible:
            state['selected_price'] = '79'
        return state

    def reset(self, task_id):
        if self.fixture is not None:
            raise RuntimeError('fixture reset may only occur once')
        self.fixture = _BY_ID[task_id]
        self.color = self.fixture.initial_color
        return {'instruction': self.fixture.query, 'observation_state': self.state(),
                'goal_options': {'private_label': _PRIVATE_MARKER}}

    def step(self, action):
        if action in {'click[白色]', 'click[黑色]'}:
            self.color = action[6:-1]
            return {'observation_state': self.state(), 'done': False}
        if action != 'click[Buy Now]':
            raise ValueError('unsupported fixture action')
        correct = self.color == '黑色'
        reward_type = 'gold_purchase' if correct else 'wrong_purchase'
        return {
            'instruction': _PRIVATE_MARKER,
            'observation_state': {'observation_version': 'shopping-observation-v2',
                'page_type': 'terminal', 'search_available': False, 'actions': []},
            'done': True, 'over': True, 'reward': int(correct),
            'reward_detail': {'reward_version': 'shopsimulator-reward-v3',
                'reward_valid': True, 'reward_type': reward_type,
                'termination_reason': reward_type, 'purchase_success': correct},
        }

    def release(self):
        self.released = True


def _client_factory(*, task_id, arm):
    # Arm is intentionally unused: no favorable C-only policy or hidden oracle.
    return ScriptedFixtureActor(recover_variant=_BY_ID[task_id].recover_variant)


def make_manifest(*, max_steps=3, max_model_calls=3, seed=20261016):
    if (type(max_steps) is not int or type(max_model_calls) is not int
            or not 1 <= max_steps <= 30 or not 1 <= max_model_calls <= 30):
        raise ValueError('offline fixture budgets must be integers between 1 and 30')
    if type(seed) is not int:
        raise ValueError('seed must be an integer')
    return ExperimentManifest(tuple(f.task_id for f in FIXTURES),
        RunConfig(max_steps=max_steps, max_model_calls=max_model_calls, seed=seed))


def _safe_destination(path):
    """Keep raw traces out of tracked source/publication trees, including symlinks."""
    root = ROOT.resolve()
    results = RESULTS_ROOT.resolve()
    destination = Path(path).expanduser().resolve()
    if not results.is_relative_to(root) or not destination.is_relative_to(results) or destination == results:
        raise ValueError('output must be a new child directory under this checkout results/')
    if destination.exists():
        raise FileExistsError('output directory exists; overwrite/resume is not supported')
    return destination


@contextmanager
def _private_creation_mode():
    old = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(old)


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode('utf-8')).hexdigest()


def _source_fingerprints():
    _require_bundled_upstream()
    manifest = json.loads((ROOT / 'UPSTREAM_MANIFEST.json').read_text())
    if manifest['source_commit'] != UPSTREAM_COMMIT:
        raise RuntimeError('upstream source identity mismatch')
    pinned = {item['path']: item['published_sha256'] for item in manifest['files']
              if item['included'] and item['path'].startswith('src/shopping_grpo/')
              and item['path'].endswith('.py')}
    directory = ROOT / 'upstream_reference'
    actual = {path.relative_to(directory).as_posix()
              for path in (directory / 'src/shopping_grpo').rglob('*.py')}
    if not pinned or actual != set(pinned):
        raise RuntimeError('upstream Python source inventory mismatch')
    fingerprints = {}
    for path, expected in sorted(pinned.items()):
        source = directory / path
        if source.is_symlink() or not source.resolve().is_relative_to(directory.resolve()):
            raise RuntimeError('upstream source must be a bundled regular file')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != expected:
            raise RuntimeError('upstream Python source hash mismatch')
        fingerprints['upstream_reference/' + path] = digest
    # Hash all local evaluation/prototype dependencies, not just the entrypoint.
    paths = {'project_paths.py', 'shopping_demo/core.py', 'UPSTREAM_MANIFEST.json'}
    paths.update(path.relative_to(ROOT).as_posix()
                 for folder in ('evaluation', 'prototype')
                 for path in (ROOT / folder).glob('*.py'))
    fingerprints.update({path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                         for path in sorted(paths)})
    return dict(sorted(fingerprints.items()))


def build_public_outputs(rows, manifest):
    """Allowlisted projections only. Raw traces remain private, not share-ready."""
    report = summarize(rows, manifest=manifest)
    # Wall-clock timing/UUIDs/timestamps are not reproducible performance metrics.
    for arm in report['arms'].values():
        arm.pop('latency_seconds')
        arm['scripted_actor_calls'] = arm.pop('model_calls')
    report.update({
        'schema_version': 'offline-scripted-baseline-summary-v1',
        'fixture_suite': SUITE_VERSION, 'warning': WARNING,
        'experiment_sha256': manifest.sha256,
        'external_model_requests': 0, 'real_simulator_tasks': 0,
        'performance_claim_permitted': False,
        'sample_scope': 'Five original synthetic cases; not development-20 or final-200 tasks.',
        'actor_responds_to_compilation': False,
        'measurement_note': 'Calls are local scripted-actor invocations; token counts and costs are unmeasured, not zero estimates.',
        'contains_queries_observations_or_private_labels': False,
    })
    failure = analyze_failures(rows, manifest=manifest)
    replay = []
    for row in rows:
        if row['arm'] == 'C' and row['trajectory'].get('initial_result'):
            result = verify_gate_replay(row)
            replay.append({'task_id': row['task_id'], **result})
    provenance = {
        'schema_version': 'offline-scripted-baseline-provenance-v1',
        'fixture_suite': SUITE_VERSION, 'execution_kind': 'mocked_smoke', 'warning': WARNING,
        'manifest': manifest.to_dict(), 'experiment_sha256': manifest.sha256,
        'fixture_count': len(FIXTURES), 'task_arm_slots': len(manifest.schedule()),
        'fixtures': [{'task_id': f.task_id, 'case': f.case} for f in FIXTURES],
        'fixture_definition_sha256': _fingerprint([asdict(f) for f in FIXTURES]),
        'actor': 'ScriptedFixtureActor; same fixed per-fixture script in every arm',
        'actor_uses_compilation_or_private_scoring': False,
        'comparison_limitations': [
            'A/B equality is expected because this fixed actor ignores compilation; it cannot measure NLU effectiveness.',
            'Recovery is a predetermined same-arm-independent script, not learned reasoning from gate feedback.',
            'The five synthetic IDs are not drawn from development or held-out evaluation datasets.',
        ],
        'arms': {'A': 'upstream collector without compilation prompt or purchase gate',
                 'B': 'same actor plus query-only compilation prompt, no purchase gate',
                 'C': 'same actor plus compilation prompt and unchanged evidence purchase gate'},
        'upstream_commit': UPSTREAM_COMMIT, 'source_sha256': _source_fingerprints(),
        'upstream_selection': 'bundled_snapshot_only; alternate overrides/imports rejected',
        'upstream_python_manifest_verified': True,
        'gate_replay': replay, 'gate_replay_expected_rows': len(manifest.task_ids),
        'gate_replay_checked_rows': len(replay),
        'gate_replay_decisions_checked': sum(r['gate_decisions_checked'] for r in replay),
        'authenticity_verified': False,
        'real_performance_evidence': False,
        'contains_queries_observations_or_private_labels': False,
    }
    return report, failure, provenance


def run_baseline(output_dir, *, max_steps=3, max_model_calls=3, seed=20261016):
    _source_fingerprints()  # Fail before creating output or executing any slot.
    manifest = make_manifest(max_steps=max_steps, max_model_calls=max_model_calls, seed=seed)
    directory = _safe_destination(output_dir)
    with _private_creation_mode():
        directory.mkdir(parents=True, exist_ok=False)
        # run_experiment persists the manifest BEFORE any task, then each row.
        rows = run_experiment(manifest, client_factory=_client_factory,
            env_factory=ScriptedFixtureEnvironment, output_dir=directory / 'private')
        report, failure, provenance = build_public_outputs(rows, manifest)
        public = directory / 'public'
        public.mkdir()
        write_trace(public / 'summary.json', report)
        write_trace(public / 'failure_analysis.json', failure)
        write_trace(public / 'provenance.json', provenance)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=RESULTS_ROOT / 'offline-baseline-v1')
    parser.add_argument('--max-steps', type=int, default=3)
    parser.add_argument('--max-model-calls', type=int, default=3)
    parser.add_argument('--seed', type=int, default=20261016)
    args = parser.parse_args(argv)
    try:
        report = run_baseline(args.output_dir, max_steps=args.max_steps,
            max_model_calls=args.max_model_calls, seed=args.seed)
    except Exception as exc:
        # Do not echo arbitrary paths, exception bodies, credentials, or inputs.
        print(json.dumps({'status': 'blocked_or_failed', 'error_type': type(exc).__name__}), file=sys.stderr)
        return 2
    failed = bool(report['missing_task_arms'] or any(arm['error_rows'] for arm in report['arms'].values()))
    print(json.dumps({'status': 'mocked_smoke_with_errors' if failed else 'mocked_smoke_complete', 'warning': WARNING,
        'expected_rows': report['expected_rows'], 'missing_rows': len(report['missing_task_arms']),
        'arms': {arm: {key: group[key] for key in ('tasks', 'successes',
            'wrong_purchases_known', 'gate_rejections', 'scripted_actor_calls')}
            for arm, group in report['arms'].items()}}, ensure_ascii=False, sort_keys=True))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
