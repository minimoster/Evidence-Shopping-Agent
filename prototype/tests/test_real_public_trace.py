"""Replay actual reset/step public states; no model or purchase is executed here.

The hand-authored narrow-grammar query below is an INTEGRATION TEST scenario,
not the simulator's original task or a held-out task. It was chosen to exercise
1487 -> 1492 selected-price invalidation around a 1490 CNY cap. This is not an
Agent/RL rollout, benchmark success rate, or a claim of task completion.
"""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from prototype import EvidenceLedger, parse_query, verify_purchase

TRACE = Path(__file__).resolve().parents[2] / "results/public_simulator_trace.json"
ASIN = "713372262998"
# Literal test query: never derive requirements from product metadata in code.
QUERY = "标题:高档Gululu Q智能语音水杯保温杯儿童316不锈钢可爱;预算:不超过1490元"


class RealPublicTraceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not TRACE.is_file():
            raise unittest.SkipTest("optional captured real public trace not present")
        cls.rows = json.loads(TRACE.read_text(encoding="utf-8"))

    def replay(self, query=QUERY):
        ledger = EvidenceLedger()
        decisions = []
        requirements = parse_query(query)
        for row in self.rows:
            observation = row["observation"]  # Only the public state, not the outer envelope.
            ledger.ingest(observation)
            decisions.append(verify_purchase(requirements, ledger, intended_asin=ASIN,
                                             intended_options=observation.get("selected_options", {})))
        return ledger, decisions

    def test_trace_contains_five_real_public_steps(self):
        self.assertEqual(len(self.rows), 5)
        self.assertEqual([row["action"] for row in self.rows], [
            "reset", "search[保温杯]", "click[713372262998]", "click[冰河蓝]", "click[暮光粉]"
        ])
        self.assertEqual(self.rows[3]["observation"]["selected_price"], 1487.0)
        self.assertEqual(self.rows[4]["observation"]["selected_price"], 1492.0)

    def test_real_query_replay_budget_binding(self):
        ledger, decisions = self.replay()
        self.assertEqual([decision.allowed for decision in decisions], [False, False, False, True, False])
        self.assertIn("over_budget", decisions[4].reasons)
        self.assertEqual(str(decisions[3].price), "1487.0")
        self.assertEqual(str(decisions[4].price), "1492.0")
        self.assertFalse(ledger.decision_is_current(decisions[3], parse_query(QUERY)))
        self.assertEqual(len(ledger.history), 5)

    def test_real_unselected_variant_is_unknown_price(self):
        observation = self.rows[2]["observation"]
        self.assertNotIn("selected_price", observation)
        self.assertEqual(observation["product"]["price"], "1487.0 to 1492.0")
        ledger = EvidenceLedger()
        ledger.ingest(observation)
        decision = verify_purchase(parse_query(QUERY), ledger, intended_asin=ASIN, intended_options={})
        self.assertIn("price_unknown", decision.reasons)
        self.assertFalse(decision.allowed)

    def test_real_selected_color_never_reuses_previous_color(self):
        _, decisions = self.replay(QUERY + ";颜色:冰河蓝")
        self.assertTrue(decisions[3].allowed)
        self.assertIn("spec_unproven:color", decisions[4].reasons)
        self.assertIn("over_budget", decisions[4].reasons)

    def test_real_public_state_missing_capacity_evidence_blocks(self):
        _, decisions = self.replay(QUERY + ";容量:500ml")
        self.assertFalse(decisions[3].allowed)
        self.assertIn("spec_unproven:capacity", decisions[3].reasons)

    def test_real_public_schema_does_not_enable_general_nlu(self):
        _, decisions = self.replay("我想买一个保温杯，预算1490元左右，最好是蓝色")
        self.assertTrue(all(not decision.allowed for decision in decisions))
        self.assertTrue(any(reason.startswith("query:") for reason in decisions[3].reasons))

    def test_synthetic_gold_injection_into_real_snapshot_is_rejected(self):
        # This one input is explicitly a synthetic perturbation of a real state.
        observation = deepcopy(self.rows[4]["observation"])
        observation["gold_purchase"] = {"price": 1, "success": True}
        ledger = EvidenceLedger()
        ledger.ingest(observation)
        decision = verify_purchase(parse_query(QUERY), ledger, intended_asin=ASIN,
                                   intended_options=observation["selected_options"])
        self.assertFalse(decision.allowed)
        self.assertIn("observation:forbidden_or_non_public_payload", decision.reasons)


if __name__ == "__main__":
    unittest.main()
