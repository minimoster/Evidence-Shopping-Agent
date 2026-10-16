"""Manifest-bound deterministic offline orchestration; no default network path.

Explicit factories are trusted test code, NOT a network sandbox. Real execution
is disabled. Persist the manifest before execution and retain it when reporting.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, replace
import hashlib
import json
from pathlib import Path
from .runner import RunConfig, run_task, write_trace
from .dev_split import task_ids_jsonl


@dataclass(frozen=True)
class ExperimentManifest:
    task_ids: tuple[int, ...]
    config: RunConfig = RunConfig()
    split_sha256: str | None = None
    arms: tuple[str, ...] = ('A', 'B', 'C')

    def __post_init__(self):
        if not isinstance(self.task_ids, tuple) or not self.task_ids:
            raise ValueError('explicit nonempty tuple of task IDs required')
        if any(type(i) is not int or i < 0 for i in self.task_ids) or len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError('task IDs must be unique nonnegative integers')
        if self.task_ids != tuple(sorted(self.task_ids)):
            raise ValueError('task IDs must be sorted for canonical scheduling')
        if self.arms != ('A', 'B', 'C'):
            raise ValueError('development comparison requires all A/B/C arms')
        if self.config.arm != 'A':
            raise ValueError('common base config must use A; orchestration selects each arm')
        if self.split_sha256 is not None and (len(self.split_sha256) != 64 or any(c not in '0123456789abcdef' for c in self.split_sha256)):
            raise ValueError('invalid split digest')

    def schedule(self):
        return [(task_id, arm) for index, task_id in enumerate(self.task_ids)
                for arm in self.arms[index % 3:] + self.arms[:index % 3]]

    def to_dict(self):
        return {'schema_version': 'evidence-experiment-manifest-v1',
                'task_ids': list(self.task_ids), 'arms': list(self.arms),
                'config': asdict(self.config), 'split_sha256': self.split_sha256,
                'schedule': [{'task_id': t, 'arm': a} for t, a in self.schedule()],
                'expected_rows': len(self.task_ids) * len(self.arms)}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or value.get('schema_version') != 'evidence-experiment-manifest-v1':
            raise ValueError('invalid experiment manifest')
        plan = cls(tuple(value['task_ids']), RunConfig(**value['config']),
                   value.get('split_sha256'), tuple(value['arms']))
        if value != plan.to_dict():
            raise ValueError('manifest schedule or expected count is not canonical')
        return plan

    @property
    def sha256(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def load_development_manifest(split_path, tasks_path, *, config=RunConfig()):
    """Consume the ID-only selector output and verify bytes before scheduling.

    This checks consistency, not provenance authenticity. dev_split selection
    owns the source/final-exclusion checks. Do not use arbitrary untrusted files.
    """
    raw = Path(split_path).read_bytes()
    split = json.loads(raw)
    tasks = Path(tasks_path).read_bytes()
    if (split.get('schema_version') != 'shopping-development-split-v1' or
        split.get('split_role') != 'development_only' or
        split.get('contains_queries_or_labels') is not False or
        split.get('final_exclusion', {}).get('task_count') != 200 or
        split.get('final_exclusion', {}).get('selected_overlap_count') != 0 or
        split.get('final_exclusion', {}).get('source_overlap_count') != 0):
        raise ValueError('not a validated development split')
    ids = split.get('task_ids')
    if not isinstance(ids, list) or len(ids) != 20:
        raise ValueError('development split must contain 20 IDs')
    plan = ExperimentManifest(tuple(ids), config, hashlib.sha256(raw).hexdigest())
    if tasks != task_ids_jsonl(ids) or hashlib.sha256(tasks).hexdigest() != split.get('tasks_jsonl_sha256'):
        raise ValueError('task bytes/hash do not match split manifest')
    return plan


def incomplete_row(plan, task_id, arm, *, status='missing', error_type=None):
    """An explicit denominator row, not a fabricated completed trajectory."""
    return {'schema_version': 'evidence-dev-evaluation-v1', 'task_id': task_id,
        'arm': arm, 'execution_kind': plan.config.execution_kind,
        'config': asdict(replace(plan.config, arm=arm)), 'experiment_sha256': plan.sha256,
        'success': False, 'purchased': False, 'wrong_purchase': None,
        'purchase_outcome_unknown': status == 'missing',
        'parser': None, 'parser_ready': False, 'gate_events': [],
        'gate_false_rejection': None, 'dispatched_steps': 0, 'executed_steps': 0,
        'budget_steps': 0, 'model_calls': 0, 'usage': [], 'latency_seconds': 0,
        'measurement_complete': False,
        'trajectory': {'status': status, 'error': {'type': error_type} if error_type else None,
                       'steps': [], 'messages': []}}


def complete_results(rows, manifest):
    """Validate expected identity/config and add every absent task-arm row."""
    if not isinstance(manifest, ExperimentManifest):
        raise TypeError('expected ExperimentManifest')
    expected = set(manifest.schedule())
    keyed = {}
    for row in rows:
        key = (row['task_id'], row['arm'])
        if key not in expected or key in keyed:
            raise ValueError('unexpected or duplicate task-arm result')
        if row.get('experiment_sha256') != manifest.sha256:
            raise ValueError('result missing or mismatching experiment binding')
        if row.get('config') != asdict(replace(manifest.config, arm=key[1])):
            raise ValueError('result configuration does not match manifest')
        if row.get('execution_kind') != manifest.config.execution_kind:
            raise ValueError('result execution kind does not match manifest')
        keyed[key] = row
    missing = [key for key in manifest.schedule() if key not in keyed]
    return [keyed.get(key) or incomplete_row(manifest, *key) for key in manifest.schedule()], missing


def run_experiment(manifest, *, client_factory, env_factory, output_dir=None):
    """Fresh client/environment per task-arm; no default network-capable adapter.

    Optional output directory is exclusive and must not already exist. Manifest
    is persisted first. KeyboardInterrupt propagates; later reporting from the
    persisted manifest fills all absent rows rather than shrinking denominator.
    Exceptions are recorded by type only. No automatic retries or resume.
    """
    if manifest.config.execution_kind != 'mocked_smoke':
        raise ValueError('real execution remains disabled')
    if client_factory is None or env_factory is None:
        raise ValueError('explicit fixture factories required')
    directory = Path(output_dir) if output_dir is not None else None
    if directory:
        directory.mkdir(parents=True, exist_ok=False)
        write_trace(directory / 'manifest.json', manifest.to_dict())
    rows = []
    for task_id, arm in manifest.schedule():
        config = replace(manifest.config, arm=arm)
        try:
            client = client_factory(task_id=task_id, arm=arm)
            row = run_task(task_id, client, config=config, env_factory=env_factory)
            row['experiment_sha256'] = manifest.sha256
            row['measurement_complete'] = True
        except Exception as exc:
            row = incomplete_row(manifest, task_id, arm, status='setup_or_runner_error', error_type=type(exc).__name__)
            # A failure outside the collector may have happened after dispatch.
            row['purchase_outcome_unknown'] = True
        rows.append(row)
        if directory:
            write_trace(directory / f'{task_id}-{arm}.json', row)
    return rows
