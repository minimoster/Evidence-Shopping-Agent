"""Original adversarial cases, independent of dev20; no NLU/model quality claim."""
from copy import deepcopy
import hashlib
import json
import unittest
from unittest.mock import Mock

from evaluation.intent_proposals import (
    SCHEMA, OfflineProposal, bounded_proposal, inspect_intent, validate_proposal,
)
from evaluation.runner import RunConfig, run_task
from evaluation.semantic_readiness import summarize_query
from tests_evaluation.test_runner import FakeClient, FakeEnvironment

QUERY = "想买适合夜跑的耳机，花费大约九十元。"


def natural_proposal():
    # Independently authored fixture. Neither these interpretations nor the
    # number conversion have been validated just because source text is exact.
    return {"schema": SCHEMA, "query_sha256": hashlib.sha256(QUERY.encode()).hexdigest(),
            "segments": [{"start": 0, "end": len(QUERY), "text": QUERY, "role": "constraint"}],
            "predicates": [{"kind": "function", "key": "use_case", "operator": "requires",
                            "values": ["适合夜跑"], "unit": None, "strength": "hard", "source_spans": [0]}],
            "budget": {"classification": "approximate_target", "amounts": ["90"], "currency": "CNY",
                       "comparator": "target", "approximate": True, "source_spans": [0]}}


class ProposalBoundaryTests(unittest.TestCase):
    def test_structurally_valid_natural_proposal_is_not_semantically_verified(self):
        p = natural_proposal()
        self.assertEqual(validate_proposal(QUERY, p), ())
        r = inspect_intent(QUERY, mode="offline_fixture", fixture=OfflineProposal(p))
        self.assertEqual(r["source_check"], "valid")
        self.assertEqual(r["semantic_acceptance"], "needs_clarification")
        self.assertIn("semantic_entailment_not_established", r["issues"])
        self.assertFalse(r["purchase_authorized"])

    def test_hallucinated_function_with_exact_span_is_still_unverified(self):
        p = natural_proposal()
        p["predicates"][0]["values"] = ["能够潜水"]
        p["budget"].update(classification="explicit_ceiling", comparator="le", approximate=False)
        self.assertEqual(validate_proposal(QUERY, p), ())
        r = inspect_intent(QUERY, mode="offline_fixture", fixture=OfflineProposal(p))
        self.assertEqual(r["semantic_acceptance"], "unverified")
        self.assertFalse(r["purchase_authorized"])

    def test_context_relabeling_cannot_drop_requirements(self):
        p = natural_proposal()
        p["segments"][0]["role"] = "context"
        p["predicates"] = []
        p["budget"] = {"classification": "absent", "amounts": [], "currency": None,
                       "comparator": None, "approximate": None, "source_spans": []}
        self.assertEqual(validate_proposal(QUERY, p), ())
        self.assertNotEqual(inspect_intent(QUERY, mode="offline_fixture", fixture=OfflineProposal(p))["semantic_acceptance"], "rule_verified")

    def test_schema_extra_keys_cannot_claim_confirmation(self):
        for name in ["confirmed", "confidence", "purchase_authorized", "gold", "model_agrees"]:
            p = natural_proposal()
            p[name] = True
            self.assertTrue(validate_proposal(QUERY, p))

    def test_span_digest_and_reference_failures(self):
        mutations = [lambda p: p.update(query_sha256="0" * 64),
                     lambda p: p["segments"][0].update(start=True),
                     lambda p: p["segments"][0].update(end=len(QUERY) - 1),
                     lambda p: p["segments"][0].update(text="改写后的原句"),
                     lambda p: p["segments"].append(deepcopy(p["segments"][0])),
                     lambda p: p["predicates"][0].update(source_spans=[10]),
                     lambda p: p["predicates"][0].update(source_spans=[True]),
                     lambda p: p["segments"][0].update(role="layout")]
        for mutate in mutations:
            p = natural_proposal()
            mutate(p)
            self.assertEqual(inspect_intent(QUERY, mode="offline_fixture", fixture=OfflineProposal(p))["semantic_acceptance"], "rejected")

    def test_bad_numeric_budget_types_and_nonfinite_values(self):
        for value in [True, 90.0, "NaN", "Infinity", "-1", "0", "9e2", "1" * 300]:
            p = natural_proposal()
            p["budget"]["amounts"] = [value]
            self.assertTrue(validate_proposal(QUERY, p))

    def test_ceiling_requires_amount_currency_comparator_and_no_approximation(self):
        for field, value in [("amounts", []), ("currency", None), ("comparator", "target"), ("approximate", True)]:
            p = natural_proposal()
            p["budget"].update(classification="explicit_ceiling", comparator="le", approximate=False)
            p["budget"][field] = value
            self.assertTrue(validate_proposal(QUERY, p))

    def test_range_and_unknown_budget_do_not_select_maximum(self):
        p = natural_proposal()
        p["budget"].update(classification="range", amounts=["70", "90"], comparator="range", approximate=False)
        self.assertEqual(validate_proposal(QUERY, p), ())
        r = inspect_intent(QUERY, mode="offline_fixture", fixture=OfflineProposal(p))
        self.assertEqual(r["proposed_budget_classification"], "range")
        self.assertIn("hard_budget_not_established", r["issues"])
        self.assertNotIn("maximum", json.dumps(r))

    def test_existing_budget_diagnostics_are_not_general_nlu(self):
        cases = [("品类:杯子;预算不超过73元", "explicit_ceiling"),
                 ("品类:杯子;预算约73元", "approximate_target"),
                 ("品类:杯子;最好预算不超过73元", "soft_target"),
                 ("品类:杯子;预算73元", "nominal_target"),
                 ("品类:杯子", "absent_or_unrecognized"),
                 ("品类:杯子;预算不超过73元;预算不超过81元", "ambiguous")]
        for q, expected in cases:
            r = inspect_intent(q)
            self.assertEqual(r["rule_budget_classification"], expected)
            self.assertEqual(r["semantic_acceptance"], "not_proposed")
            self.assertFalse(r["rule_budget_is_general_nlu"])

    def test_bounded_bridge_is_explicit_and_cannot_authorize_purchase(self):
        q = "品类:杯子;预算不超过73元;容量至少500mL"
        p = bounded_proposal(q)
        self.assertEqual(validate_proposal(q, p), ())
        r = inspect_intent(q, mode="offline_fixture", fixture=OfflineProposal(p))
        self.assertEqual(r["semantic_acceptance"], "rule_verified")
        self.assertFalse(r["purchase_authorized"])
        p["predicates"][-1]["operator"] = "le"
        self.assertEqual(validate_proposal(q, p), ())
        self.assertEqual(inspect_intent(q, mode="offline_fixture", fixture=OfflineProposal(p))["semantic_acceptance"], "unverified")

    def test_unknown_predicates_and_strength_need_clarification(self):
        p = natural_proposal()
        p["predicates"][0].update(kind="unknown", operator="unknown", strength="uncertain", values=[])
        self.assertEqual(validate_proposal(QUERY, p), ())
        self.assertIn("unresolved_intent", inspect_intent(QUERY, mode="offline_fixture", fixture=OfflineProposal(p))["issues"])

    def test_bad_shapes_are_rejected_without_exceptions(self):
        for bad in [None, [], {"schema": SCHEMA}]:
            self.assertTrue(validate_proposal(QUERY, bad))
        for key in ["classification", "currency", "comparator", "approximate"]:
            p = natural_proposal()
            p["budget"][key] = {}
            self.assertTrue(validate_proposal(QUERY, p))

    def test_provider_callbacks_and_real_mode_are_never_dispatched(self):
        provider = Mock()
        for mode in ["disabled", "offline_fixture", "real_model"]:
            with self.assertRaises(ValueError):
                inspect_intent(QUERY, mode=mode, fixture=provider)
        provider.propose.assert_not_called()

    def test_source_resource_limits_and_input_type(self):
        for q in ["x" * 4097, "x" * 257, " " * 9]:
            self.assertTrue(validate_proposal(q, {}))
        with self.assertRaises(TypeError):
            inspect_intent({"query": QUERY, "task_id": 1})

    def test_unicode_offsets_and_unknown_units_do_not_imply_semantics(self):
        query = "想要🪁图案的轻便水杯"
        p = natural_proposal()
        p["query_sha256"] = hashlib.sha256(query.encode()).hexdigest()
        p["segments"] = [{"start": 0, "end": len(query), "text": query, "role": "constraint"}]
        p["predicates"][0].update(kind="quantity", key="weight", operator="le", values=["1", "unknown-unit"], unit="unknown-unit")
        self.assertEqual(validate_proposal(query, p), ())
        r = inspect_intent(query, mode="offline_fixture", fixture=OfflineProposal(p))
        self.assertNotEqual(r["semantic_acceptance"], "rule_verified")
        self.assertFalse(r["purchase_authorized"])


class ProposalIntegrationTests(unittest.TestCase):
    def test_existing_readiness_retains_counts_and_reports_disabled_mode(self):
        row = summarize_query("品类:杯子;预算不超过73元")
        self.assertTrue(row["canonical_ready"])
        self.assertTrue(row["bounded_semantics_ready"])
        self.assertEqual(row["intent_boundary"]["mode"], "disabled")
        self.assertEqual(row["intent_boundary"]["proposal_model_calls"], 0)

    def test_valid_but_unverified_proposal_cannot_bypass_original_c_gate(self):
        env = FakeEnvironment()
        reset = env.reset
        def natural_reset(task_id):
            value = reset(task_id)
            value["instruction"] = QUERY
            return value
        env.reset = natural_reset
        p = natural_proposal()
        p["budget"].update(classification="explicit_ceiling", comparator="le", approximate=False)
        client = FakeClient([("buy_now", {})])
        row = run_task(7, client, config=RunConfig(arm="C", max_steps=1, max_model_calls=1,
                       proposal_mode="offline_fixture"), proposal_fixture=OfflineProposal(p),
                       env_factory=lambda **kw: env)
        self.assertEqual(row["intent_boundary"]["source_check"], "valid")
        self.assertEqual(row["intent_boundary"]["semantic_acceptance"], "unverified")
        self.assertFalse(row["gate_events"][0]["decision"]["allowed"])
        self.assertEqual(env.actions, [])
        self.assertNotIn("untrusted-intent-proposal-v1", json.dumps(client.messages))

    def test_default_runner_logs_disabled_boundary_without_a_provider(self):
        row = run_task(7, FakeClient([("buy_now", {})]), config=RunConfig(arm="C", max_steps=1, max_model_calls=1), env_factory=lambda **kw: FakeEnvironment())
        self.assertEqual(row["intent_boundary"]["proposal_status"], "disabled")
        self.assertEqual(row["intent_boundary"]["semantic_acceptance"], "not_proposed")

    def test_real_mode_and_fixture_misconfiguration_fail_before_environment(self):
        with self.assertRaises(ValueError):
            RunConfig(proposal_mode="real_model")
        with self.assertRaises(ValueError):
            RunConfig(execution_kind="real_model_real_simulator", proposal_mode="offline_fixture")
        factory = Mock()
        with self.assertRaises(ValueError):
            run_task(7, FakeClient([]), proposal_fixture=OfflineProposal(natural_proposal()), env_factory=factory)
        factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
