"""Bounded deterministic JSON-input stress checks, not shopping evaluations.

All perturbed inputs are synthetic. Starting shape is copied from a captured
public state, but mutated prices/specs are not claimed as real observations.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import random

from prototype import EvidenceLedger, parse_query, verify_purchase

ROOT = Path(__file__).resolve().parent


def main():
    rng = random.Random(20261015)
    trace = json.loads((ROOT / "results/public_simulator_trace.json").read_text())
    public = trace[3]["observation"]
    query = "标题:高档Gululu Q智能语音水杯保温杯儿童316不锈钢可爱;预算:不超过1490元"
    requirements = parse_query(query)
    scalar = [None, False, True, -1, 0, 0.01, 1490, 1490.01, "", "unknown", "NaN", "1490", "1487 to 1492"]
    values = scalar + [[], {}, [None], ["x"], {"颜色": None}, {"颜色分类": "冰河蓝"}, ["buy now"]]
    keys = list(public) + ["goal", "reward_detail", "gold_purchase"]
    for index in range(3000):
        observation = deepcopy(public)
        if index % 5 == 0:
            observation = deepcopy(rng.choice(values))
        else:
            observation[rng.choice(keys)] = deepcopy(rng.choice(values))
        # Guarantee inputs are JSON-representable, not custom executable objects.
        observation = json.loads(json.dumps(observation))
        outputs = []
        for _ in range(2):
            ledger = EvidenceLedger()
            snapshot = ledger.ingest(observation)
            decision = verify_purchase(requirements, ledger, intended_asin="713372262998",
                                       intended_options=public["selected_options"])
            outputs.append(decision.to_dict())
            if decision.allowed:
                assert not snapshot.issues
                assert decision.price is not None and decision.price <= requirements.budget.maximum
                assert snapshot.page_type == "product_detail"
                assert decision.asin == "713372262998"
                assert ledger.decision_is_current(decision, requirements)
        assert outputs[0] == outputs[1], (index, observation)
    alphabet = "预算不超过以下以内元标题颜色品牌;:，；\n 黑白0123456789.万k左右ABC¥￥≤<>"
    for _ in range(2000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 100)))
        result = parse_query(text)
        spans = list(result.unparsed)
        for spec in result.specs:
            spans.extend([spec.span, spec.value_span])
        if result.budget:
            spans.extend([result.budget.span, result.budget.amount_span])
        for span in spans:
            assert text[span.start:span.end] == span.text
    summary = {"kind": "deterministic_synthetic_JSON_stress_not_agent_evaluation",
               "seed": 20261015, "observation_cases": 3000,
               "observation_verifications": 6000, "query_cases": 2000,
               "uncaught_exceptions": 0, "determinism_mismatches": 0,
               "span_mismatches": 0, "model_or_api_calls": 0}
    (ROOT / "results/robustness_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
