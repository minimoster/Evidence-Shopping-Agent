"""Reset-only dev20 adapter for bounded semantics; no step, model or purchase.

Uses the existing pinned runtime and exact existing split. Never filters out
unsupported tasks, substitutes synthetic queries or persists original queries.
The public reset instruction is the compiler's only input; reset observations
are validated separately and cannot manufacture product evidence or solvability.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

from .constraints import compile_query
from .semantic_constraints import VERSION, accept_semantics, propose_constraints


def summarize_query(query: str) -> dict:
    """Pure query adapter, with no IDs, observations, persona or gold input."""
    proposal = propose_constraints(query)
    accepted = accept_semantics(query, proposal)
    statuses = Counter(c["status"] for c in proposal["clauses"])
    return {"query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "canonical_ready": compile_query(query).ready,
            "bounded_semantics_ready": accepted.ready,
            "issues": list(accepted.issues), "clause_status_counts": dict(statuses),
            "hard_predicate_count": sum(c["node"] is not None and c["node"]["strength"] == "hard" for c in proposal["clauses"]),
            "product_evidence_status": "not_collected", "task_solvability": "not_assessed"}


def validate_semantic_resets(runtime) -> dict:
    """Retain every task slot, including reset/release failures, without steps."""
    from .local_simulator import LocalSimulatorRuntime
    from shopping_demo.core import _check_public_tree

    if type(runtime) is not LocalSimulatorRuntime or not runtime.verified:
        raise TypeError("a verified pinned LocalSimulatorRuntime is required")
    rows = []
    aborted = False
    for task_id in runtime.task_ids:
        row = {"task_id": task_id, "status": "unattempted", "released": False}
        rows.append(row)
        if aborted:
            continue
        client = None
        try:
            client = runtime.env_factory()
            result = client.reset(task_id)
            _check_public_tree(result["observation_state"])
            if result["observation_state"].get("page_type") != "search_home":
                raise ValueError("unexpected reset page")
            row.update(summarize_query(result["instruction"]))
            row["status"] = "measured"
        except Exception:
            # Private exception bodies and query text are never report fields.
            row["status"] = "reset_or_analysis_failed"
            aborted = True
        finally:
            if client is not None:
                try:
                    client.release()
                    row["released"] = client.env_idx is None and runtime.active_leases == 0
                except Exception:
                    row["released"] = False
                if not row["released"]:
                    row["status"] = "release_failed"
                    aborted = True
    return {"schema": VERSION, "execution_kind": "real_simulator_reset_only_no_model",
            "task_count": len(rows), "measured_count": sum(r["status"] == "measured" for r in rows),
            "canonical_ready_count": sum(r.get("canonical_ready", False) and r["status"] == "measured" for r in rows),
            "bounded_semantics_ready_count": sum(r.get("bounded_semantics_ready", False) and r["status"] == "measured" for r in rows),
            "rows": rows, "tasks_jsonl_sha256": runtime.split_manifest["tasks_jsonl_sha256"],
            "query_text_persisted": False, "simulator_steps": 0, "model_calls": 0,
            "product_evidence_collected": False, "solvability_assessed": False,
            "final200_queries_or_labels_examined": False}


def main(argv=None):
    import argparse
    import sys
    from .local_simulator import LocalSimulatorRuntime
    from offline_checks import deny_external_actions

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--split-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    sys.addaudithook(deny_external_actions)
    # Reserve a new output before loading assets. Persist completed accounting
    # even if cleanup fails; never claim success for a failed runtime close.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        runtime = None
        summary = {"schema": VERSION, "status": "runtime_unavailable", "task_count": 20,
                   "measured_count": 0, "bounded_semantics_ready_count": None,
                   "model_calls": 0, "simulator_steps": 0}
        try:
            runtime = LocalSimulatorRuntime(args.runtime_dir, split_dir=args.split_dir)
            summary = validate_semantic_resets(runtime)
            summary["status"] = "completed" if summary["measured_count"] == 20 else "incomplete"
        except Exception:
            # Avoid dumping local paths, private query or exception payloads.
            summary["status"] = "runtime_or_validation_failed"
        finally:
            if runtime is not None:
                try:
                    runtime.close()
                except Exception:
                    summary["status"] = "runtime_cleanup_failed"
            json.dump(summary, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}))
    return 0 if summary["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
