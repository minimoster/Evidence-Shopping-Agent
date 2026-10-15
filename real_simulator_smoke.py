"""Deterministic scripted exercise of the actual simulator, no model or API.

Decisions use only structured_observation(), never server goal/annotations,
gold ASIN, reward details, or the raw product corpus. Dataset loading and
indexing happen inside the unmodified simulator as expected by its runtime.
No purchase is submitted and no benchmark success claim is made.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

from offline_checks import DENIED_EVENTS, deny_external_actions

ROOT = Path(__file__).resolve().parent
from project_paths import upstream_path
UPSTREAM = upstream_path()
SHOP = UPSTREAM / "environments/ShopSimulator/shop_env"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-purchase-gate", action="store_true",
                        help="Verify the new rule gate on each freshly obtained public state; never buy")
    args = parser.parse_args()
    sys.addaudithook(deny_external_actions)
    sys.path[:0] = [str(UPSTREAM / "src"), str(SHOP)]
    os.environ["SHOP_SEARCH_INDEX"] = str(ROOT / "runtime/products.sqlite3")
    from web_agent_site.envs.web_agent_text_env import WebAgentTextEnv

    started = time.monotonic()
    ledger = None
    decisions = []
    if args.with_purchase_gate:
        from prototype import EvidenceLedger, parse_query, verify_purchase
        ledger = EvidenceLedger()
        # Explicit test scenario, not the original simulator task, not inferred
        # from product annotations. No benchmark/task-completion claim.
        requirements = parse_query("标题:高档Gululu Q智能语音水杯保温杯儿童316不锈钢可爱;预算:不超过1490元")
    env = WebAgentTextEnv(observation_mode="text", file_path=str(ROOT / "runtime/items_eval_train.json"))
    trace = []

    def record(action, status=None):
        public = env.structured_observation()
        # Never record simulator status payloads, which can contain labels.
        trace.append({"action": action, "observation": public,
                      "done": bool((status or {}).get("done", False))})
        assert not {"goal", "reward", "reward_detail", "purchase", "trace_target"} & public.keys()
        if ledger is not None:
            ledger.ingest(public)
            decision = verify_purchase(requirements, ledger,
                                       intended_asin="713372262998",
                                       intended_options=public.get("selected_options", {}))
            decisions.append(decision)
            trace[-1]["gate_decision"] = decision.to_dict()
        return public

    env.reset(idx=0, session="offline-smoke-0")
    state = record("reset")
    assert state["page_type"] == "search_home"
    _, status, _ = env.step("search[保温杯]")
    state = record("search[保温杯]", status)
    assert state["page_type"] == "search_results"
    assert state["products"] and len(state["products"]) <= 20
    available = env.get_available_actions()
    clickables = [value for value in available["clickables"] if value != "search"]
    # Same public-text footer format as shop_env/shop_agent.py, without
    # importing its logger or accepting its full goal/reward-bearing envelope.
    legacy = env.observation + (
        f"\n\n搜索功能是否可用: {available['has_search_bar']}"
        f"\n\n可点击的按钮: {json.dumps(clickables, ensure_ascii=False)}")
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results/public_legacy_search.txt").write_text(legacy)
    asin = state["products"][0]["asin"]
    assert asin in state["actions"]
    _, status, _ = env.step(f"click[{asin}]")
    state = record(f"click[{asin}]", status)
    assert state["page_type"] == "product_detail"
    assert state["product"]["asin"] == asin
    # Select the first visible value on each axis, not hidden target options.
    first_options = dict(state["available_options"])
    for axis, values in first_options.items():
        if values:
            value = values[0]
            assert value in state["actions"]
            _, status, _ = env.step(f"click[{value}]")
            state = record(f"click[{value}]", status)
            assert state["selected_options"][axis] == value
    # Switch one visible variant to exercise price rebinding.
    switched = False
    for axis, values in first_options.items():
        if len(values) > 1:
            value = values[1]
            assert value in state["actions"]
            _, status, _ = env.step(f"click[{value}]")
            state = record(f"click[{value}]", status)
            assert state["selected_options"][axis] == value
            switched = True
            break
    assert not any(row["done"] for row in trace)
    env.close()
    env.server.search_engine.close()
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    trace_name = "live_gate_trace.json" if ledger is not None else "public_simulator_trace.json"
    (out / trace_name).write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n")
    summary = {"suite": "real_simulator_scripted_smoke", "reset_calls": 1,
               "step_calls": len(trace)-1, "public_observations": len(trace),
               "first_search_page_products": len(trace[1]["observation"]["products"]),
               "total_search_results": trace[1]["observation"]["total_results"],
               "opened_asin": asin, "visible_option_axes": len(first_options),
               "variant_switch_exercised": switched, "purchases_submitted": 0,
               "legacy_public_search_captured": True,
               "model_calls": 0, "external_api_calls": 0, "external_network": "denied",
               "blocked_external_action_attempts": list(DENIED_EVENTS),
               "success_rate": "not measured; no agent or policy evaluation",
               "elapsed_seconds": round(time.monotonic()-started, 3)}
    summary_name = "real_simulator_summary.json"
    if ledger is not None:
        assert [decision.allowed for decision in decisions] == [False, False, False, True, False]
        assert "over_budget" in decisions[-1].reasons
        assert not ledger.decision_is_current(decisions[3], requirements)
        summary.update({"suite": "live_public_state_purchase_gate_smoke",
                        "gate_decisions": [decision.allowed for decision in decisions],
                        "gate_prices": [str(decision.price) if decision.price is not None else None for decision in decisions],
                        "last_gate_reasons": list(decisions[-1].reasons),
                        "old_variant_decision_invalidated": True,
                        "requirements_source": "hand-authored explicit integration-test query; not original simulator task",
                        "gate_query": requirements.query})
        summary_name = "live_gate_summary.json"
    (out / summary_name).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
