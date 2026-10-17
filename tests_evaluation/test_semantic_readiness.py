"""Synthetic adapter failure tests. No actual dev queries or model calls."""
import json
import unittest
from unittest.mock import patch

from evaluation.semantic_readiness import summarize_query, validate_semantic_resets


class FakeRuntime:
    verified = True
    task_ids = tuple(range(20))
    split_manifest = {"tasks_jsonl_sha256": "synthetic_test_only"}

    def __init__(self, failure=None):
        self.failure = failure
        self.active_leases = 0
        self.resets = []
        self.releases = 0

    def env_factory(self):
        owner = self
        class Client:
            env_idx = None

            def reset(self, task_id):
                owner.resets.append(task_id)
                self.env_idx = 0
                owner.active_leases = 1
                if owner.failure == "reset" and task_id == 2:
                    raise RuntimeError("PRIVATE_ERROR_BODY")
                return {"instruction": "品类:水杯;预算不超过80元;容量至少500mL",
                        "goal_options": {"attribute": "HIDDEN_GOLD_NOT_PRODUCT_FACT"},
                        "observation_state": {"page_type": "search_home", "actions": []}}

            def release(self):
                owner.releases += 1
                if owner.failure == "release":
                    raise RuntimeError("PRIVATE_RELEASE_BODY")
                owner.active_leases = 0
                self.env_idx = None

            def step(self, *args):
                raise AssertionError("readiness must never interact or purchase")
        return Client()


class SemanticReadinessTests(unittest.TestCase):
    def measure(self, runtime):
        with patch("evaluation.local_simulator.LocalSimulatorRuntime", FakeRuntime):
            return validate_semantic_resets(runtime)

    def test_query_summary_has_no_raw_text_or_solvability_claim(self):
        row = summarize_query("品类:水杯;预算不超过80元;容量至少500mL")
        self.assertTrue(row["bounded_semantics_ready"])
        self.assertFalse(row["canonical_ready"])
        self.assertEqual(row["task_solvability"], "not_assessed")
        self.assertEqual(row["product_evidence_status"], "not_collected")
        self.assertNotIn("水杯", json.dumps(row, ensure_ascii=False))

    def test_missing_budget_and_unsupported_intent_remain_in_denominator(self):
        for q in ["品类:水杯", "品类:水杯;预算约80元", "品类:水杯;预算不超过80元;必须保温"]:
            row = summarize_query(q)
            self.assertFalse(row["bounded_semantics_ready"])
            self.assertTrue(row["issues"])

    def test_all_twenty_resets_are_retained_without_gold_or_steps(self):
        runtime = FakeRuntime()
        summary = self.measure(runtime)
        self.assertEqual(summary["task_count"], 20)
        self.assertEqual(summary["measured_count"], 20)
        self.assertEqual(runtime.releases, 20)
        self.assertEqual(summary["simulator_steps"], 0)
        self.assertEqual(summary["model_calls"], 0)
        self.assertNotIn("HIDDEN_GOLD", json.dumps(summary))
        self.assertNotIn("水杯", json.dumps(summary, ensure_ascii=False))

    def test_reset_failure_aborts_without_dropping_unattempted_slots(self):
        runtime = FakeRuntime("reset")
        summary = self.measure(runtime)
        self.assertEqual(summary["task_count"], 20)
        self.assertEqual(summary["measured_count"], 2)
        self.assertEqual(summary["rows"][2]["status"], "reset_or_analysis_failed")
        self.assertEqual(summary["rows"][-1]["status"], "unattempted")
        self.assertEqual(runtime.releases, 3)
        self.assertNotIn("PRIVATE_ERROR_BODY", json.dumps(summary))

    def test_release_failure_is_reported_and_stops_next_reset(self):
        runtime = FakeRuntime("release")
        summary = self.measure(runtime)
        self.assertEqual(summary["task_count"], 20)
        self.assertEqual(summary["measured_count"], 0)
        self.assertEqual(summary["bounded_semantics_ready_count"], 0)
        self.assertEqual(summary["rows"][0]["status"], "release_failed")
        self.assertEqual(runtime.resets, [0])
        self.assertNotIn("PRIVATE_RELEASE_BODY", json.dumps(summary))

    def test_unverified_or_arbitrary_runtime_is_rejected(self):
        with self.assertRaises(TypeError):
            validate_semantic_resets(FakeRuntime())
        runtime = FakeRuntime()
        runtime.verified = False
        with self.assertRaises(TypeError):
            self.measure(runtime)


if __name__ == "__main__":
    unittest.main()
