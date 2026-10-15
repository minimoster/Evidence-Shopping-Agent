"""All examples here are synthetic narrow-grammar cases, not benchmark tasks."""
from dataclasses import replace
from decimal import Decimal
import unittest

from prototype import parse_query


class QueryRulesTest(unittest.TestCase):
    def test_explicit_budget_and_specs_with_original_spans(self):
        query = "  品类：耳机 ； 预算：不超过100.50元； 颜色:黑色 "
        req = parse_query(query)
        self.assertTrue(req.ready, req.issues)
        self.assertEqual(req.budget.maximum, Decimal("100.50"))
        for span in [req.budget.span, req.budget.amount_span,
                     *(s.span for s in req.specs), *(s.value_span for s in req.specs)]:
            self.assertEqual(query[span.start:span.end], span.text)
        self.assertEqual(req.budget.amount_span.text, "100.50")

    def test_strict_and_inclusive_comparators(self):
        for op in ("不超过", "不高于", "最多", "<=", "≤"):
            with self.subTest(op=op):
                self.assertTrue(parse_query(f"品类:耳机;预算:{op}100元").budget.inclusive)
        for op in ("低于", "少于", "<"):
            with self.subTest(op=op):
                self.assertFalse(parse_query(f"品类:耳机;预算:{op}100元").budget.inclusive)

    def test_suffix_budget(self):
        self.assertEqual(parse_query("品类:耳机;预算:100元以内").budget.maximum, Decimal(100))

    def test_explicit_cny_prefix(self):
        for prefix in ("¥", "￥", "CNY ", "人民币"):
            with self.subTest(prefix=prefix):
                self.assertTrue(parse_query(f"品类:耳机;预算:不超过{prefix}100").ready)

    def test_missing_budget(self):
        self.assertFalse(parse_query("品类:耳机;颜色:黑色").ready)

    def test_missing_currency(self):
        req = parse_query("品类:耳机;预算:不超过100")
        self.assertIn("budget_currency_missing", req.issues)
        self.assertFalse(req.ready)

    def test_bare_budget_not_assumed_maximum(self):
        self.assertFalse(parse_query("品类:耳机;预算:100元").ready)

    def test_approximate_budget_fails_closed(self):
        self.assertFalse(parse_query("品类:耳机;预算:100元左右").ready)

    def test_range_budget_fails_closed(self):
        self.assertFalse(parse_query("品类:耳机;预算:100-200元").ready)

    def test_scaled_budget_fails_closed(self):
        self.assertFalse(parse_query("品类:耳机;预算:不超过1万元").ready)

    def test_other_currency_fails_closed(self):
        self.assertFalse(parse_query("品类:耳机;预算:不超过$100").ready)

    def test_duplicate_equal_budgets_still_ambiguous(self):
        req = parse_query("品类:耳机;预算:不超过100元;预算:不超过100元")
        self.assertIn("multiple_budgets", req.issues)
        self.assertIsNone(req.budget)

    def test_conflicting_budgets(self):
        req = parse_query("品类:耳机;预算:不超过100元;预算:不超过200元")
        self.assertFalse(req.ready)

    def test_duplicate_spec_aliases(self):
        self.assertIn("duplicate_spec:color", parse_query("品类:耳机;预算:不超过100元;颜色:黑色;color:红色").issues)

    def test_unknown_clause_retained_and_blocks(self):
        query = "品类:耳机;预算:不超过100元;必须支持降噪"
        req = parse_query(query)
        self.assertFalse(req.ready)
        self.assertEqual(req.unparsed[0].text, "必须支持降噪")
        self.assertEqual(query[req.unparsed[0].start:req.unparsed[0].end], "必须支持降噪")

    def test_soft_or_alternative_specs_fail_closed(self):
        for value in ("黑色或白色", "黑色/白色", "黑色优先", "黑色左右", "不限", "不要白色"):
            with self.subTest(value=value):
                self.assertFalse(parse_query(f"品类:耳机;预算:不超过100元;颜色:{value}").ready)

    def test_missing_product_scope(self):
        self.assertIn("product_scope_missing", parse_query("预算:不超过100元;颜色:黑色").issues)

    def test_query_only_type_contract(self):
        with self.assertRaises(TypeError):
            parse_query({"instruction": "品类:耳机", "gold_purchase": True})

    def test_empty_query(self):
        self.assertFalse(parse_query("").ready)

    def test_nonpositive_budget(self):
        self.assertIn("budget_not_positive", parse_query("品类:耳机;预算:不超过0元").issues)

    def test_budget_rounding_is_never_invented(self):
        self.assertFalse(parse_query("品类:耳机;预算:不超过100.001元").ready)

    def test_json_friendly_audit(self):
        req = parse_query("品类:耳机;预算:不超过100元")
        self.assertEqual(req.to_dict()["budget"]["maximum"], "100")
        self.assertIn("not-general-NLU", req.to_dict()["parser"])


if __name__ == "__main__":
    unittest.main()
