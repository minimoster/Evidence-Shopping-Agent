"""Explicit-denominator metrics. Unknown labels/costs never become zeros."""
from itertools import combinations


def _rate(numerator, denominator):
    return numerator / denominator if denominator else None


def summarize(rows, *, manifest=None):
    missing = []
    if manifest is not None:
        from .experiment import complete_results
        rows, missing = complete_results(rows, manifest)
    if not rows:
        raise ValueError("empty evaluation")
    kinds = {r["execution_kind"] for r in rows}
    if len(kinds) != 1:
        raise ValueError("cannot mix mocked and real evaluation")
    keyed = {}
    for row in rows:
        key = (row["arm"], row["task_id"])
        if key in keyed:
            raise ValueError("duplicate task/arm; repetitions need separate reports")
        keyed[key] = row
    arms = {}
    for arm in sorted({r["arm"] for r in rows}):
        group = [r for r in rows if r["arm"] == arm]
        n = len(group)
        purchases = sum(r["purchased"] for r in group)
        unknown = sum((r["purchased"] and r["wrong_purchase"] is None) or r.get("purchase_outcome_unknown", False) for r in group)
        wrong = sum(r["wrong_purchase"] is True for r in group)
        usage = [u for r in group for u in r["usage"]]
        totals = {}
        for key in ("input_tokens", "output_tokens", "cost_usd"):
            known = [u[key] for u in usage if u.get(key) is not None]
            totals[key] = sum(known) if len(known) == len(usage) and all(r.get("measurement_complete", True) for r in group) else None
            totals[key + "_known_calls"] = len(known)
        coverage = [(r.get("parser") or {}).get("audit", {}).get("coverage", {}) for r in group]
        clause_totals = {key: sum(c.get(key, 0) for c in coverage) for key in
            ("total_clauses", "supported_clauses", "unsupported_clauses", "ambiguous_clauses")}
        rejected = sum(e["executed"] is False for r in group for e in r["gate_events"])
        arms[arm] = {"tasks": n,
            "missing_rows": sum(r['trajectory']['status'] == 'missing' for r in group),
            "aborted_unattempted_rows": sum(r["trajectory"]["status"] == "aborted_unattempted" for r in group),
            "error_rows": sum(r['trajectory']['status'] in {'error', 'setup_or_runner_error', 'environment_release_failed'} for r in group),
            "successes": sum(r["success"] for r in group),
            "all_task_success_rate": sum(r["success"] for r in group) / n,
            "purchases": purchases, "wrong_purchases_known": wrong,
            "unadjudicated_purchases": unknown,
            "uncertain_purchase_dispatches": sum(r.get("purchase_outcome_unknown", False) for r in group),
            "wrong_purchase_all_task_rate": None if unknown else wrong / n,
            "wrong_purchase_conditioned_rate": None if unknown else _rate(wrong, purchases),
            "gate_rejections": rejected,
            "gate_false_rejection_rate": None,
            "gate_false_rejection_denominator": "independently adjudicated valid candidate purchase attempts (not available)",
            "parser_ready_tasks": sum(r["parser_ready"] for r in group),
            "parser_ready_rate": sum(r["parser_ready"] for r in group) / n,
            "parser_clause_coverage": {**clause_totals, "supported_fraction":
                _rate(clause_totals["supported_clauses"], clause_totals["total_clauses"])},
            "executed_steps": sum(r["executed_steps"] for r in group),
            "budget_steps": sum(r["budget_steps"] for r in group),
            "model_calls": sum(r["model_calls"] for r in group),
            "latency_seconds": sum(r["latency_seconds"] for r in group), **totals}
    paired = {}
    for a, b in combinations(arms, 2):
        ia = {r["task_id"] for r in rows if r["arm"] == a}
        ib = {r["task_id"] for r in rows if r["arm"] == b}
        common = sorted(ia & ib)
        mismatches = []
        for task_id in common:
            left = {k: v for k, v in keyed[a, task_id]["config"].items() if k != "arm"}
            right = {k: v for k, v in keyed[b, task_id]["config"].items() if k != "arm"}
            if left != right:
                mismatches.append(task_id)
        paired[a + "_vs_" + b] = {"complete_pairing": ia == ib,
            "comparable_configurations": not mismatches,
            "configuration_mismatch_task_ids": mismatches,
            "paired_tasks": len(common), "unmatched_tasks": sorted(ia ^ ib),
            "both_success": sum(keyed[a, i]["success"] and keyed[b, i]["success"] for i in common),
            "a_only_success": sum(keyed[a, i]["success"] and not keyed[b, i]["success"] for i in common),
            "b_only_success": sum(not keyed[a, i]["success"] and keyed[b, i]["success"] for i in common),
            "neither_success": sum(not keyed[a, i]["success"] and not keyed[b, i]["success"] for i in common),
            "outcomes": [{"task_id": i, a: {k: keyed[a, i][k] for k in ("success", "purchased", "wrong_purchase")},
                          b: {k: keyed[b, i][k] for k in ("success", "purchased", "wrong_purchase")}} for i in common]}
    return {"manifest_checked": manifest is not None,
            "expected_rows": len(manifest.schedule()) if manifest else None,
            "missing_task_arms": [{'task_id': t, 'arm': a} for t, a in missing],
            "execution_kind": next(iter(kinds)), "arms": arms, "paired": paired,
            "warning": "Mocked smoke results are not real LLM/simulator performance." if kinds == {"mocked_smoke"} else None}
