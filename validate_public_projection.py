"""Validate canonical rendering/projection on genuine captured public states.

Uses character counts as an explicit deterministic proxy, NOT model token counts.
No tokenizer, model, benchmark or hidden label is loaded.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

from offline_checks import deny_external_actions

ROOT = Path(__file__).resolve().parent


def main():
    sys.addaudithook(deny_external_actions)
    from project_paths import upstream_path
    sys.path.insert(0, str(upstream_path() / "src"))
    from shopping_grpo.environment.actions import product_ids
    from shopping_grpo.environment.observation import render_structured_observation
    from shopping_grpo.environment.projection import ObservationProjectionError, project_observation
    rows = json.loads((ROOT / "results/public_simulator_trace.json").read_text())
    results = []
    for row in rows:
        state = row["observation"]
        raw = render_structured_observation(state)
        projected, meta = project_observation("captured_public_smoke", raw, count_tokens=len)
        assert meta.critical_footer_preserved
        assert set(product_ids(raw)) == set(product_ids(projected))
        results.append({"action": row["action"], "page_type": state["page_type"],
                        "raw_characters": len(raw), "visible_characters": len(projected),
                        "product_ids_preserved": len(product_ids(projected)),
                        "footer_preserved": True})
    raw_search = render_structured_observation(rows[1]["observation"])
    low_budget_closed = False
    try:
        project_observation("search_products", raw_search, count_tokens=len, token_budget=64)
    except ObservationProjectionError:
        low_budget_closed = True
    assert low_budget_closed
    assert results[1]["product_ids_preserved"] == 20
    summary = {"kind": "canonical_v2_projection_on_captured_real_public_states",
               "counter": "Python len characters, not a model tokenizer",
               "public_states_checked": len(results), "results": results,
               "impossibly_small_budget_fails_closed": low_budget_closed,
               "hidden_labels_used": False, "model_or_api_calls": 0}
    (ROOT / "results/public_projection_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
