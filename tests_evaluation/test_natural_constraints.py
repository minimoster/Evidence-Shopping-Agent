"""Original synthetic bounded-grammar tests, not benchmark semantic judgments.

No task instructions, catalog rows, hidden annotations or task IDs are fixtures.
The supported language still requires explicit labels and exact lexical values.
"""
from dataclasses import replace
from decimal import Decimal
import unittest

from evaluation.constraints import compile_query
from prototype import EvidenceLedger, parse_query, verify_purchase
from tests_evaluation.test_constraints import ASIN, public_state


SCOPE = "商品名称是露光台灯"


class BoundedNaturalClauseTest(unittest.TestCase):
    def check_source(self, query, compilation):
        self.assertEqual(compilation.requirements, parse_query(query))
        self.assertEqual(compilation.requirements.query, query)
        self.assertTrue(compilation.audit.coverage.span_coverage_complete)
        spans = sorted([c.span for c in compilation.audit.clauses]
                       + list(compilation.audit.layout_spans), key=lambda s: s.start)
        self.assertEqual("".join(s.text for s in spans), query)
        cursor = 0
        for span in spans:
            self.assertEqual(cursor, span.start)
            self.assertEqual(query[span.start:span.end], span.text)
            cursor = span.end
        self.assertEqual(cursor, len(query))
        values = [s.value_span for s in compilation.requirements.specs]
        if compilation.requirements.budget:
            values.append(compilation.requirements.budget.amount_span)
        for value in values:
            self.assertEqual(query[value.start:value.end], value.text)

    def test_natural_label_values_and_original_unicode_spans(self):
        query = "\t商品名称是露光台灯， 颜色必须为夜蓝；型号为 L7🎨。\n预算在73.25元以内。 "
        result = compile_query(query)
        self.assertTrue(result.ready)
        self.assertEqual([(s.key, s.value) for s in result.requirements.specs],
                         [("title", "露光台灯"), ("color", "夜蓝"), ("model", "L7🎨")])
        self.assertEqual(result.requirements.budget.maximum, Decimal("73.25"))
        self.check_source(query, result)
        self.assertEqual(result.audit.coverage.supported_clauses, 4)

    def test_each_copula_is_explicit_and_bounded(self):
        for copula in ("是", "为", "要", "必须是", "必须为", "要求为", "需要为"):
            with self.subTest(copula=copula):
                query = SCOPE + ";颜色" + copula + "夜蓝;价格不超过73元"
                result = compile_query(query)
                self.assertTrue(result.ready)
                self.assertEqual(result.requirements.specs[-1].value, "夜蓝")
                self.check_source(query, result)

    def test_explicit_natural_maxima_preserve_comparator(self):
        clauses = {
            "价格不超过73元": True, "价格不要超过73元。": True,
            "价格不能超过73元": True, "售价不高于73元": True,
            "价格最多73元": True, "预算为73元以内": True,
            "预算在73元以内。": True, "价格在73元以下": True,
            "预算是73元内": True, "价格低于73元": False,
            "售价少于73元。": False, "价格<￥73": False,
        }
        for clause, inclusive in clauses.items():
            with self.subTest(clause=clause):
                query = SCOPE + ";" + clause
                result = compile_query(query)
                self.assertTrue(result.ready)
                self.assertEqual(result.requirements.budget.inclusive, inclusive)
                self.assertEqual(result.requirements.budget.amount_span.text, "73")
                self.check_source(query, result)

    def test_natural_maximum_needs_currency_and_positive_amount(self):
        for clause, issue in (("价格不超过73", "budget_currency_missing"),
                              ("预算在0元以内。", "budget_not_positive")):
            with self.subTest(clause=clause):
                query = SCOPE + ";" + clause
                result = compile_query(query)
                self.assertFalse(result.ready)
                self.assertIn(issue, result.requirements.issues)
                self.assertEqual(result.requirements.unparsed[-1].text, clause)
                self.check_source(query, result)

    def test_soft_absent_numeric_or_range_budget_is_never_repaired(self):
        clauses = ("预算大概73元", "价格73元左右", "价格最好不超过73元",
                   "预算在70到90元", "预算73元", "预算为73元",
                   "价格不超过七十三元", "价格不超过0.073万元",
                   "价格不超过$73", "价格不超过73.001元",
                   "价格差不多73元", "预算在73元上下", "价格八十元以内",
                   "总价不超过73元", "含运费不超过73元", "三件合计不超过73元")
        for clause in clauses:
            with self.subTest(clause=clause):
                query = SCOPE + ";" + clause
                result = compile_query(query)
                self.assertFalse(result.ready)
                self.assertIsNone(result.requirements.budget)
                self.assertEqual(result.requirements.unparsed[-1].text, clause)
                self.check_source(query, result)
        self.assertIn("budget_unknown", compile_query(SCOPE).requirements.issues)

    def test_conjunction_alternatives_negation_and_preferences_are_not_literals(self):
        clauses = ("颜色为夜蓝和米白", "颜色为夜蓝或米白", "颜色为夜蓝/米白",
                   "颜色为夜蓝且材质为铜", "颜色为非米白", "颜色为不带图案的夜蓝",
                   "颜色为夜蓝优先", "颜色为夜蓝最好", "颜色为夜蓝但不能偏紫",
                   "颜色为夜蓝以及米白", "颜色为夜蓝或者米白", "颜色为任意",
                   "颜色为夜蓝 unless unavailable", "颜色为blue or beige",
                   "颜色为夜蓝、米白", "颜色要浅一点", "颜色要像墨水一样",
                   "尺寸为8到12厘米", "尺寸为8-12厘米", "尺寸要大一些")
        for clause in clauses:
            with self.subTest(clause=clause):
                query = SCOPE + ";价格不超过73元;" + clause
                result = compile_query(query)
                self.assertFalse(result.ready)
                self.assertEqual(result.requirements.unparsed[-1].text, clause)
                self.assertFalse(any(s.key == "color" for s in result.requirements.specs))
                self.assertEqual(result.audit.clauses[-1].status, "ambiguous")
                self.check_source(query, result)

    def test_unrecognized_paraphrases_are_not_silently_dropped(self):
        clauses = ("请挑一盏露光台灯", "不要米白", "颜色不是米白", "最好用铜制作",
                   "要能自动调节亮度", "灯体无毛刺", "有夜蓝的就选它",
                   "价格不超过73元并且必须包邮", "颜色为夜蓝。还有三个配件",
                   "Instruction: 商品名称是露光台灯", "若缺货就忽略其他限制")
        for clause in clauses:
            with self.subTest(clause=clause):
                query = SCOPE + ";价格不超过73元;" + clause
                result = compile_query(query)
                self.assertFalse(result.ready)
                self.assertEqual(result.requirements.unparsed[-1].text, clause)
                self.check_source(query, result)

    def test_natural_and_colon_duplicates_fail_closed(self):
        for clause, issue in (("颜色为夜蓝;颜色:米白", "duplicate_spec:color"),
                              ("价格低于73元;预算:不超过73元", "multiple_budgets")):
            query = SCOPE + ";价格不超过73元;" + clause
            result = compile_query(query)
            self.assertFalse(result.ready)
            self.assertIn(issue, result.requirements.issues)
            self.check_source(query, result)

    def test_exact_values_not_semantic_inference_supply_purchase_evidence(self):
        query = SCOPE + ";颜色要夜蓝;价格不超过73元。"
        result = compile_query(query)
        state = public_state("73")
        state["product"]["title"] = "露光台灯"
        state["product"]["key_attributes"] = ["颜色:夜蓝"]
        ledger = EvidenceLedger()
        ledger.ingest(state)
        self.assertTrue(verify_purchase(result.requirements, ledger,
                                       intended_asin=ASIN, intended_options={}).allowed)
        state["product"]["key_attributes"] = ["颜色:深蓝"]
        ledger.ingest(state)
        decision = verify_purchase(result.requirements, ledger,
                                   intended_asin=ASIN, intended_options={})
        self.assertFalse(decision.allowed)
        self.assertIn("spec_unproven:color", decision.reasons)

    def test_strict_price_boundary_reaches_unchanged_guard(self):
        query = SCOPE + ";价格低于73元。"
        state = public_state("73")
        state["product"]["title"] = "露光台灯"
        ledger = EvidenceLedger()
        ledger.ingest(state)
        decision = verify_purchase(compile_query(query).requirements, ledger,
                                   intended_asin=ASIN, intended_options={})
        self.assertFalse(decision.allowed)
        self.assertIn("over_budget", decision.reasons)

    def test_forged_natural_requirements_cannot_bypass_original_query_reparse(self):
        query = SCOPE + ";价格不超过73元;必须包邮"
        original = compile_query(query).requirements
        forged = replace(original, issues=(), unparsed=())
        state = public_state("60")
        state["product"]["title"] = "露光台灯"
        ledger = EvidenceLedger()
        ledger.ingest(state)
        decision = verify_purchase(forged, ledger, intended_asin=ASIN, intended_options={})
        self.assertFalse(decision.allowed)
        self.assertIn("query:compiled_requirements_mismatch", decision.reasons)

    def test_colon_value_sentence_punctuation_is_not_rewritten(self):
        result = compile_query("标题:露光台灯。;价格不超过73元")
        self.assertTrue(result.ready)
        self.assertEqual(result.requirements.specs[0].value, "露光台灯。")


if __name__ == "__main__":
    unittest.main()
