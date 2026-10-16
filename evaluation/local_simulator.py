"""Pinned real simulator, in process, with the upstream client/lease lifecycle.

No server, model, credentials, network, GPU or real-world purchase is used here.
The simulator alone loads its frozen corpus/labels. Reset is restricted to the
20 verified development IDs; policy code sees the original user-visible query
and public observation, never goal options/persona/gold. Terminal reward fields
are private scoring data and must pass through EvaluationEnvironment before an
Actor. Final-200 query/label files are never opened by this module.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing, contextmanager
from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time

from project_paths import ROOT, UPSTREAM_COMMIT, upstream_path
from .dev_split import (
    BLIND_IDS_KEY, DEFAULT_SEED, _load_candidate_ids, _load_final_ids,
    _manifest_entry, _verify_pinned_bytes, task_ids_jsonl,
)


# This adapter is bounded to the prepared, authorized default-seed dev20 set.
# A different ID set requires a new reviewed selection, not rewritten metadata.
PREPARED_DEV20_TASKS_SHA256 = "5b1dce23e1c1c7bc462da7bb931746facc57259156f848843c2939c0fb412990"


class SimulatorValidationError(ValueError):
    """The supplied local assets do not match pinned provenance."""


def sha256_file(path):
    with Path(path).open("rb") as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_development_split(split_dir=ROOT / "runtime/dev20", *, upstream=None):
    """Validate saved selection, blind IDs and source provenance without queries."""
    upstream = Path(upstream or upstream_path()).resolve()
    split_dir = Path(split_dir).resolve()
    metadata = _json(split_dir / "manifest.json")
    data = (split_dir / "tasks.jsonl").read_bytes()
    ids = _load_candidate_ids(data)
    provenance_path = ROOT / "UPSTREAM_MANIFEST.json"
    provenance = _json(provenance_path)
    source = metadata.get("source", {})
    if provenance.get("source_commit") != UPSTREAM_COMMIT or source.get("commit") != UPSTREAM_COMMIT:
        raise SimulatorValidationError("development split has wrong upstream commit")
    if source.get("path") not in {"data/grpo/train.jsonl", "data/grpo/validation.jsonl"}:
        raise SimulatorValidationError("development split has invalid source role")
    entry = _manifest_entry(provenance, source["path"])
    if (source.get("git_blob_sha1") != entry["source_git_blob_sha1"]
            or source.get("bytes") != entry["source_bytes"]
            or source.get("provenance_manifest_sha256") != sha256_file(provenance_path)):
        raise SimulatorValidationError("development split source provenance mismatch")
    blind_bytes = (upstream / BLIND_IDS_KEY).read_bytes()
    _verify_pinned_bytes(blind_bytes, _manifest_entry(provenance, BLIND_IDS_KEY), "blind IDs")
    blind = _load_final_ids(blind_bytes)
    if len(ids) != 20 or ids != sorted(ids) or set(ids) & blind:
        raise SimulatorValidationError("require exactly 20 sorted, distinct, non-final task IDs")
    if (metadata.get("schema_version") != "shopping-development-split-v1"
            or metadata.get("split_role") != "development_only"
            or metadata.get("contains_queries_or_labels") is not False
            or metadata.get("task_ids") != ids
            or metadata.get("selection", {}).get("seed") != DEFAULT_SEED
            or metadata.get("selection", {}).get("task_count") != 20
            or hashlib.sha256(data).hexdigest() != metadata.get("tasks_jsonl_sha256")
            or hashlib.sha256(data).hexdigest() != PREPARED_DEV20_TASKS_SHA256
            or data != task_ids_jsonl(ids)
            or metadata.get("final_exclusion", {}).get("sha256") != hashlib.sha256(blind_bytes).hexdigest()):
        raise SimulatorValidationError("saved development split metadata mismatch")
    return ids, metadata


def verify_runtime_assets(runtime_dir, *, upstream=None):
    """Hash data, index and included upstream sources without inspecting labels."""
    upstream = Path(upstream or upstream_path()).resolve()
    runtime_dir = Path(runtime_dir).resolve()
    provenance = _json(ROOT / "UPSTREAM_MANIFEST.json")
    if provenance.get("source_commit") != UPSTREAM_COMMIT:
        raise SimulatorValidationError("wrong pinned upstream commit")
    checked = 0
    for item in provenance["files"]:
        key = item["path"]
        needed = (key == "data/environment.json" or key.startswith("src/shopping_grpo/")
                  or key.startswith("environments/ShopSimulator/shop_env/"))
        if not item["included"] or not needed:
            continue
        path = upstream / key
        if path.is_symlink() or not path.is_file():
            raise SimulatorValidationError("missing or symlinked upstream source: " + key)
        _verify_pinned_bytes(path.read_bytes(), item, key)
        checked += 1
    manifest = _json(upstream / "data/environment.json")
    shop = upstream / "environments/ShopSimulator/shop_env"
    config = _json(shop / "configs/environment.json")
    for key in ("environment_version", "search", "reward", "observation_version", "tool_version"):
        if config[key] != manifest[key]:
            raise SimulatorValidationError("environment config mismatch: " + key)
    if config["termination"]["max_steps"] != manifest["max_steps"]:
        raise SimulatorValidationError("environment step limit mismatch")
    product_sha = sha256_file(runtime_dir / "items_eval_train.json")
    external = _json(runtime_dir / "products.manifest.json")
    index_sha = sha256_file(runtime_dir / "products.sqlite3")
    if product_sha != manifest["product_data_sha256"] or product_sha != external.get("product_data_sha256"):
        raise SimulatorValidationError("product data SHA256 mismatch")
    if index_sha != external.get("index_sha256"):
        raise SimulatorValidationError("index SHA256 mismatch")
    uri = (runtime_dir / "products.sqlite3").as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        internal = json.loads(connection.execute("SELECT payload FROM manifest").fetchone()[0])
        product_count = connection.execute("SELECT count(*) FROM products").fetchone()[0]
    if internal != {key: value for key, value in external.items() if key != "index_sha256"}:
        raise SimulatorValidationError("internal and external index manifests differ")
    if (internal.get("search_version") != manifest["search"]["version"]
            or internal.get("field_weights") != manifest["search"]["field_weights"]
            or product_count != internal.get("product_count")):
        raise SimulatorValidationError("index search contract mismatch")
    # This is an upstream metadata discrepancy, not a local source modification.
    # Publication SHA256 AND original Git-blob pins were already checked above.
    runtime_hash_mismatches = []
    for name, expected in manifest["runtime_files_sha256"].items():
        matches = list(shop.rglob(name))
        if len(matches) != 1:
            raise SimulatorValidationError("ambiguous pinned runtime file: " + name)
        actual = sha256_file(matches[0])
        if actual != expected:
            runtime_hash_mismatches.append({"file": name, "manifest_sha256": expected,
                "pinned_source_sha256": actual, "source_git_blob_verified": True})
    return {"source_commit": UPSTREAM_COMMIT, "shopsimulator_commit": manifest["shopsimulator_commit"],
        "environment_version": manifest["environment_version"], "observation_version": manifest["observation_version"],
        "reward_version": manifest["reward"]["version"], "tool_version": manifest["tool_version"],
        "search_version": manifest["search"]["version"], "max_steps": manifest["max_steps"],
        "product_data_sha256": product_sha, "index_sha256": index_sha, "product_count": product_count,
        "index_manifests_match": True, "verified_upstream_files": checked,
        "upstream_runtime_manifest_discrepancies": runtime_hash_mismatches}


_IMPORT_LOCK = threading.RLock()


@contextmanager
def _runtime_environment(runtime_dir, upstream):
    values = {"SHOP_SEARCH_INDEX": str(runtime_dir / "products.sqlite3"),
              "SHOP_ENV_CONFIG": str(upstream / "environments/ShopSimulator/shop_env/configs/environment.json"),
              "SHOP_MAX_STEPS": "35"}
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _load_runtime_types(upstream, log_dir):
    shop = upstream / "environments/ShopSimulator/shop_env"
    for path in (upstream / "src", shop):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    # Upstream import opens a relative log file. Confine that side effect to an
    # ignored local runtime directory; simulator source and functions stay intact.
    log_dir.mkdir(parents=True, exist_ok=True)
    with _IMPORT_LOCK:
        cwd = Path.cwd()
        try:
            os.chdir(log_dir)
            agent = importlib.import_module("shop_env.shop_agent")
        finally:
            os.chdir(cwd)
        agent.logger.disabled = True  # Do not log queries/actions/private data.
        text_env = importlib.import_module("web_agent_site.envs.web_agent_text_env")
        leases = importlib.import_module("shop_env.slot_lease_pool")
        client = importlib.import_module("shopping_grpo.environment.client")
        observation = importlib.import_module("shopping_grpo.environment.observation")
    for module in (agent, text_env, leases, client, observation):
        if not Path(module.__file__).resolve().is_relative_to(upstream):
            raise SimulatorValidationError("an imported runtime module is not from pinned upstream")
    return text_env.WebAgentTextEnv, leases.SlotLeasePool, client.ShopAgentEnv, agent.shop_agent, observation.render_structured_observation


class LocalSimulatorRuntime:
    """One sequential upstream simulator slot with real ShopAgentEnv clients.

    ``env_factory`` can be injected unchanged into the existing collector. The
    runtime owns the frozen corpus and scorer; each client owns exactly one lease.
    ``close`` rejects active leases rather than silently freeing another client.
    """
    execution_kind = "real_simulator"

    def __init__(self, runtime_dir, *, split_dir=ROOT / "runtime/dev20", upstream=None,
                 log_dir=ROOT / "runtime/local_simulator"):
        self.upstream = Path(upstream or upstream_path()).resolve()
        self.runtime_dir = Path(runtime_dir).resolve()
        self.task_ids, self.split_manifest = verify_development_split(split_dir, upstream=self.upstream)
        self.verified = False
        self.validation = verify_runtime_assets(self.runtime_dir, upstream=self.upstream)
        Env, Pool, self._Client, self._handle, self._render = _load_runtime_types(self.upstream, Path(log_dir))
        with _IMPORT_LOCK, _runtime_environment(self.runtime_dir, self.upstream):
            self._env = Env(observation_mode="text", split="train", num_products=None,
                session_prefix="bounded-dev-slot-0", file_path=str(self.runtime_dir / "items_eval_train.json"))
        self._pool = Pool(1)
        self._lock = threading.RLock()
        self._closed = False
        if self._env.server.environment_version != self.validation["environment_version"]:
            self._env.server.search_engine.close()
            raise SimulatorValidationError("loaded environment version differs")
        self.verified = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    @property
    def active_leases(self):
        return 1 - len(self._pool.free_slots())

    def env_factory(self, *, base_url="http://127.0.0.1:5700", timeout=60):
        if self._closed:
            raise RuntimeError("local simulator is closed")
        # URL exists only to satisfy the unchanged client contract. The supplied
        # transport never opens a connection, regardless of the base_url value.
        return self._Client(base_url=base_url, timeout=timeout, transport=self._transport)

    def _transport(self, endpoint, payload, timeout):
        with self._lock:
            if self._closed:
                raise RuntimeError("local simulator is closed")
            action = payload.get("action")
            if action == "reset":
                task_id = payload.get("idx")
                if type(task_id) is not int or task_id not in self.task_ids:
                    raise ValueError("only verified development task IDs are allowed")
                if payload.get("include_trace_target"):
                    raise ValueError("hidden trace targets are forbidden")
                slot = self._pool.acquire()
                if slot is None:
                    raise RuntimeError("local simulator slot is already leased")
                try:
                    raw = self._handle(self._env, slot, "reset", task_id, include_trace_target=False)
                    # Never return goal_options, instruction_simple or persona.
                    result = {key: deepcopy(raw[key]) for key in
                        ("instruction", "observation_state", "environment_version", "env_idx", "idx")}
                except BaseException:
                    self._pool.release(slot)
                    raise
            elif action == "interact":
                if payload.get("env_idx") != 0 or self.active_leases != 1:
                    raise RuntimeError("interaction requires an active local lease")
                raw = self._handle(self._env, 0, "interact", response=payload["response"])
                # Raw terminal HTML text contains labels. Always render public
                # structured state; preserve only scoring fields privately.
                allowed = ("done", "reward", "reward_detail", "over", "termination_reason",
                           "reward_valid", "observation_state", "env_idx", "idx")
                result = {key: deepcopy(raw[key]) for key in allowed if key in raw}
                result["instruction"] = self._render(result["observation_state"])
            elif action == "release_one":
                if payload.get("env_idx") != 0:
                    raise ValueError("invalid local slot")
                released = self._pool.release(0)
                result = {"message": "Environment 0 has been released" if released else "Environment 0 is already free"}
            else:
                raise ValueError("unsupported local simulator action")
            return {"result": result}

    def close(self):
        with self._lock:
            if self._closed:
                return
            if self.active_leases:
                raise RuntimeError("release the active client before closing the simulator")
            self._env.close()
            self._env.server.search_engine.close()
            self._closed = True
            self.verified = False


def validate_resets(runtime):
    """Only reset/release and compile public queries; never step or persist text."""
    from .constraints import compile_query
    from shopping_demo.core import _check_public_tree
    rows = []
    issues = Counter()
    for task_id in runtime.task_ids:
        client = runtime.env_factory()
        try:
            result = client.reset(task_id)
            state = result["observation_state"]
            _check_public_tree(state)
            if state["page_type"] != "search_home":
                raise SimulatorValidationError("reset did not return search_home")
            compilation = compile_query(result["instruction"])
            issues.update(compilation.requirements.issues)
            rows.append({"task_id": task_id, "reset_valid": True, "parser_ready": compilation.ready,
                         "coverage": compilation.audit.coverage.to_dict()})
        finally:
            client.release()
        rows[-1]["released"] = client.env_idx is None and runtime.active_leases == 0
    return {"suite": "real_simulator_dev20_reset_validation", "execution_kind": "real_simulator_no_model",
        **runtime.validation, "task_count": len(rows), "successful_resets": len(rows),
        "successful_releases": sum(row["released"] for row in rows),
        "tasks_jsonl_sha256": runtime.split_manifest["tasks_jsonl_sha256"],
        "parser_ready_count": sum(row["parser_ready"] for row in rows), "parser_issues": dict(issues),
        "rows": rows, "query_text_persisted": False, "final200_queries_or_labels_examined": False,
        "simulator_steps": 0, "simulator_purchases": 0, "real_world_purchases": 0, "model_calls": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--split-dir", type=Path, default=ROOT / "runtime/dev20")
    parser.add_argument("--output", type=Path, default=ROOT / "results/local_simulator_validation.json")
    args = parser.parse_args(argv)
    from offline_checks import DENIED_EVENTS, deny_external_actions
    sys.addaudithook(deny_external_actions)
    started = time.monotonic()
    with LocalSimulatorRuntime(args.runtime_dir, split_dir=args.split_dir) as runtime:
        summary = validate_resets(runtime)
    summary.update({"external_network": "denied", "blocked_external_action_attempts": list(DENIED_EVENTS),
                    "elapsed_seconds": round(time.monotonic() - started, 3)})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({key: value for key, value in summary.items() if key != "rows"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
