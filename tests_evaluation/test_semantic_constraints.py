"""Independent authored boundary cases, not dev tasks or model performance data.

Expected outcomes are literal assertions, never computed by another parser.
All products here are synthetic; no catalog/task answers were used.
"""
from copy import deepcopy
from dataclasses import replace
from decimal import localcontext
import unittest

from evaluation.semantic_constraints import (
    accept_semantics, propose_constraints, validate_structure, verify_constraints,
)
from prototype import EvidenceLedger, parse_query, verify_purchase

ASIN = "000000000071"
BASE = "品类:水杯;预算:不超过80元"


def product(*, capacity="750mL", color="蓝色", price="79.99"):
    return {"observation_version": "shopping-observation-v2", "page_type": "product_detail", "search_available": False,
            "actions": ["buy now"], "product": {"asin": ASIN, "title": "测试杯",
                "category": "水杯", "brand": "测试品牌", "price": "1",
                "key_attributes": ["容量:" + capacity]},
            "available_options": {"颜色": ["蓝色", "白色"]},
            "selected_options": {"颜色": color}, "selected_price": price}


def accepted(query):
    return accept_semantics(query, propose_constraints(query))


def review(query, observation=None, *, ledger=None, candidate=None):
    ledger = ledger or EvidenceLedger()
    if observation is not None:
        ledger.ingest(observation)
    return verify_constraints(candidate or accepted(query), ledger, intended_asin=ASIN,
                              intended_options=dict(ledger.current.variant) if ledger.current else {})


class SemanticBoundaryTests(unittest.TestCase):
    def test_exact_and_conjunction_with_alternatives(self):
        q = BASE + ";颜色为蓝色或白色;容量至少500mL"
        p = propose_constraints(q)
        self.assertEqual(p["clauses"][2]["node"]["values"], ["蓝色", "白色"])
        self.assertTrue(accepted(q).ready)
        self.assertTrue(review(q, product())["allowed"])
        # Frozen canonical A/B/C grammar is not quietly upgraded.
        self.assertFalse(parse_query(q).ready)

    def test_numeric_boundaries_and_unit_conversion(self):
        cases = [("容量至少750mL", "0.75L", True), ("容量大于750mL", "0.75L", False),
                 ("容量不超过750mL", "750.000001mL", False), ("容量小于1L", "1000mL", False),
                 ("容量为1L", "1000毫升", True), ("容量至少1L", "999.999999mL", False)]
        for clause, value, expected in cases:
            with self.subTest(clause=clause, value=value):
                self.assertEqual(review(BASE + ";" + clause, product(capacity=value))["allowed"], expected)

    def test_ambient_decimal_precision_cannot_round_evidence(self):
        with localcontext() as context:
            context.prec = 2
            self.assertFalse(review(BASE + ";容量不超过750mL", product(capacity="750.001mL"))["allowed"])

    def test_invalid_numeric_structure_cannot_be_forged_ready(self):
        q = "品类:水杯;预算不超过1234567890123元"
        self.assertFalse(accepted(q).ready)
        self.assertFalse(review(q, product(), candidate=replace(accepted(q), issues=()))["allowed"])

    def test_closed_interval_endpoints(self):
        q = BASE + ";容量在500mL到1L之间（含两端）"
        for value, expected in [("500mL", True), ("1L", True), ("499.999mL", False), ("1.001L", False)]:
            self.assertEqual(review(q, product(capacity=value))["allowed"], expected)

    def test_range_ambiguity_and_reverse_never_repaired(self):
        for clause in ["容量在500mL到1L之间", "容量在1L到500mL之间（含两端）", "容量500-1000", "容量至少1kg"]:
            with self.subTest(clause=clause):
                self.assertFalse(accepted(BASE + ";" + clause).ready)

    def test_negation_needs_positive_selected_value(self):
        q = BASE + ";颜色不是白色"
        self.assertTrue(review(q, product(color="蓝色"))["allowed"])
        result = review(q, product(color="白色"))
        self.assertFalse(result["allowed"])
        self.assertEqual(result["predicates"][-1]["status"], "violated")
        obs = product()
        obs["selected_options"] = {}
        obs["available_options"] = {}
        obs["product"]["key_attributes"].append("颜色:蓝色")
        result = review(q, obs)
        self.assertEqual(result["predicates"][-1]["status"], "unknown")
        self.assertFalse(result["allowed"])

    def test_functional_absence_and_compatibility_not_inferred(self):
        for clause in ["不含塑料", "必须保温", "兼容我的车架", "颜色不含白色", "容量至少500mL且不漏水", "如果打折就买", "颜色:蓝色且无BPA", "属性:保温并防漏"]:
            q = BASE + ";" + clause
            obs = product()
            obs["product"]["title"] += clause
            self.assertFalse(review(q, obs)["allowed"])

    def test_budget_is_never_inferred_from_targets(self):
        for budget in ["", ";预算约80元", ";预算80元", ";最好预算不超过80元", ";预算不超过80", ";预算不超过80美元", ";总价不超过80元", ";预算不超过80元左右"]:
            q = "品类:水杯" + budget
            self.assertFalse(accepted(q).ready, q)
            self.assertFalse(review(q, product())["allowed"], q)
            self.assertFalse(any(c["node"] and c["node"]["kind"] == "budget" for c in propose_constraints(q)["clauses"]))

    def test_budget_price_boundary_is_decimal_and_variant_specific(self):
        self.assertTrue(review(BASE, product(price="80"))["allowed"])
        self.assertFalse(review(BASE, product(price="80.01"))["allowed"])
        self.assertFalse(review(BASE.replace("不超过", "低于"), product(price="80"))["allowed"])
        obs = product()
        del obs["selected_price"]
        self.assertFalse(review(BASE, obs)["allowed"])

    def test_soft_exact_is_retained_but_does_not_relax_hard_constraints(self):
        q = BASE + ";最好颜色为白色;容量至少500mL"
        result = review(q, product())
        self.assertTrue(result["allowed"], result["reasons"])
        self.assertEqual(result["predicates"][2]["node"]["strength"], "soft")
        self.assertEqual(result["predicates"][2]["status"], "violated")
        self.assertFalse(review(q, product(capacity="100mL"))["allowed"])
        self.assertFalse(accepted(BASE + ";最好颜色必须为白色").ready)

    def test_duplicate_hard_requirements_are_not_merged(self):
        for extra in [";颜色为蓝色;颜色不是白色", ";容量至少500mL;容量小于1L", ";预算不超过100元"]:
            self.assertFalse(accepted(BASE + extra).ready)

    def test_alternatives_cannot_be_dropped_or_expanded(self):
        q = BASE + ";颜色为蓝色或白色"
        for values in [["蓝色"], ["蓝色", "白色", "红色"]]:
            proposal = propose_constraints(q)
            proposal["clauses"][-1]["node"]["values"] = values
            self.assertFalse(accept_semantics(q, proposal).ready)

    def test_full_character_accounting_and_unicode_offsets(self):
        q = "  商品名称:星杯🟦；\n预算:不超过80元，容量至少500mL。  "
        p = propose_constraints(q)
        self.assertEqual(validate_structure(q, p), ())
        spans = sorted(p["layout"] + [c["span"] for c in p["clauses"]], key=lambda s: s["start"])
        self.assertEqual("".join(s["text"] for s in spans), q)
        self.assertTrue(accepted(q).ready)

    def test_structure_is_not_semantic_authority(self):
        q = BASE + ";容量至少500mL"
        p = propose_constraints(q)
        p["clauses"][-1]["node"]["operator"] = "le"
        self.assertEqual(validate_structure(q, p), ())
        self.assertFalse(accept_semantics(q, p).ready)

    def test_forged_context_and_cleared_issues_cannot_accept(self):
        q = BASE + ";必须保温"
        p = propose_constraints(q)
        clause = p["clauses"].pop()
        p["layout"].append(clause["span"])
        p["issues"] = []
        self.assertEqual(validate_structure(q, p), ())
        self.assertFalse(accept_semantics(q, p).ready)
        forged = replace(accepted(q), issues=())
        self.assertFalse(review(q, product(), candidate=forged)["allowed"])

    def test_mutated_accepted_serialization_cannot_authorize(self):
        q = BASE + ";容量至少500mL"
        forged = replace(accepted(q), canonical_json=accepted(BASE).canonical_json)
        self.assertFalse(review(q, product(), candidate=forged)["allowed"])

    def test_malformed_untrusted_proposals_fail_closed(self):
        q = BASE + ";容量至少500mL"
        mutations = [lambda p: p.update(extra=True), lambda p: p["clauses"][0].update(status=[]),
                     lambda p: p["clauses"][0]["span"].update(start=True),
                     lambda p: p["clauses"][0]["span"].update(text="tampered"),
                     lambda p: p["clauses"][-1]["node"].update(unit=[]),
                     lambda p: p["clauses"][-1]["node"].update(values=["NaN", "mL"]),
                     lambda p: p["clauses"][-1]["node"].update(values=[True, "mL"]),
                     lambda p: p["clauses"][-1]["node"].update(kind="function"),
                     lambda p: p["clauses"].pop()]
        for mutate in mutations:
            p = propose_constraints(q)
            mutate(p)
            self.assertFalse(accept_semantics(q, p).ready)

    def test_resource_limits_preserve_source(self):
        for q in ["x" * 4097, BASE + ";" + "x" * 257, BASE + " " * 9]:
            p = propose_constraints(q)
            self.assertEqual(p["clauses"][0]["span"]["text"], q)
            self.assertFalse(accepted(q).ready)

    def test_query_input_boundary(self):
        for bad in [{"query": BASE}, [BASE], None, 12]:
            with self.assertRaises(TypeError):
                propose_constraints(bad)
        with self.assertRaises(TypeError):
            propose_constraints(BASE, {"goal": "hidden"})

    def test_unknown_numeric_evidence_cannot_match_title(self):
        q = BASE + ";容量至少500mL"
        for value in ["约750mL", "500-1000mL", "NaN", "1kg", "750", "750mL或300mL"]:
            obs = product(capacity=value)
            obs["product"]["title"] = "容量:750mL"
            result = review(q, obs)
            self.assertFalse(result["allowed"])
            self.assertEqual(result["predicates"][-1]["status"], "unknown")

    def test_conflicting_or_missing_evidence_is_unknown(self):
        q = BASE + ";容量至少500mL"
        for attrs in [[], ["容量:750mL", "容量:300mL"]]:
            obs = product()
            obs["product"]["key_attributes"] = attrs
            result = review(q, obs)
            self.assertFalse(result["allowed"])
            self.assertEqual(result["predicates"][-1]["status"], "unknown")

        obs = product()
        obs["product"]["key_attributes"] = []
        obs["record"] = {"attribute": ["容量:750mL"]}
        # A task-shaped sidecar can never fill candidate product evidence.
        self.assertFalse(review(q, obs)["allowed"])

    def test_option_axis_takes_priority_over_generic_attribute(self):
        obs = product(capacity="750mL")
        obs["available_options"]["容量"] = ["300mL", "750mL"]
        obs["selected_options"]["容量"] = "300mL"
        result = review(BASE + ";容量至少500mL", obs)
        self.assertFalse(result["allowed"])
        self.assertEqual(result["predicates"][-1]["status"], "violated")

    def test_freshness_taint_and_invalid_observations(self):
        q = BASE + ";容量至少500mL"
        ledger = EvidenceLedger()
        self.assertTrue(review(q, product(), ledger=ledger)["allowed"])
        obs = product()
        obs["product"]["key_attributes"] = []
        self.assertFalse(review(q, obs, ledger=ledger)["allowed"])
        for mutation in [lambda o: o.update(goal="hidden"), lambda o: o.update(actions=[]),
                         lambda o: o["product"].update(asin="000000000072"),
                         lambda o: o.update(selected_options={}), lambda o: o.update(selected_price="NaN")]:
            obs = product()
            mutation(obs)
            self.assertFalse(review(q, obs)["allowed"])

    def test_no_observation_and_no_purchase_side_effect(self):
        result = review(BASE)
        self.assertFalse(result["allowed"])
        self.assertFalse(result["execution_performed"])
        self.assertIn("no_public_observation", result["reasons"])

    def test_canonical_guard_keeps_its_original_contract(self):
        q = BASE + ";容量至少500mL"
        ledger = EvidenceLedger()
        ledger.ingest(product())
        self.assertFalse(verify_purchase(parse_query(q), ledger, intended_asin=ASIN,
                         intended_options={"颜色": "蓝色"}).allowed)


if __name__ == "__main__":
    unittest.main()
