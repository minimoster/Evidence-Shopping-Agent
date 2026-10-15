"""Integration with the real upstream PUBLIC state builder, using synthetic products.

Only the stdlib-only observation.py builder is loaded. No task/goal loader, model,
training code, catalog ground truth or reward evaluator is imported.
"""
import inspect
from pathlib import Path
import runpy
import unittest

from prototype import EvidenceLedger, parse_query, verify_purchase

ROOT = Path(__file__).resolve().parents[2]
BUILDER_PATH = ROOT / "upstream/environments/ShopSimulator/shop_env/web_agent_site/engine/observation.py"


class UpstreamPublicSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not BUILDER_PATH.is_file():
            raise unittest.SkipTest("optional read-only upstream public builder not present")
        cls.builder = staticmethod(runpy.run_path(str(BUILDER_PATH))["build_observation_state"])

    def test_real_builder_signature_excludes_goal(self):
        self.assertNotIn("goal", inspect.signature(self.builder).parameters)

    def test_real_builder_detail_state_is_consumable(self):
        asin = "000000000001"
        public = self.builder(
            page_type="product_detail",
            session={"asin": asin, "options": {"颜色分类": "黑色"}, "selected_price": 80.0},
            product_item_dict={asin: {"asin": asin, "title": "测试耳机", "category": "耳机",
                "brand": "合成测试品牌", "pricing": [1, 180], "attribute": ["防水"],
                "options": {"颜色分类": ["黑色", "白色"]}}},
            available_actions={"has_search_bar": False, "clickables": ["buy now", "黑色", "白色"]},
        )
        ledger = EvidenceLedger()
        snapshot = ledger.ingest(public)
        self.assertEqual(snapshot.issues, ())
        decision = verify_purchase(parse_query("品类:耳机;预算:不超过100元;颜色:黑色"), ledger,
                                   intended_asin=asin, intended_options={"颜色分类": "黑色"})
        self.assertTrue(decision.allowed, decision.reasons)
        self.assertEqual(decision.price, 80)

    def test_real_builder_omits_unknown_selected_price_and_gate_blocks(self):
        asin = "000000000001"
        public = self.builder(
            page_type="product_detail", session={"asin": asin, "options": {"颜色": "黑色"}, "selected_price": None},
            product_item_dict={asin: {"asin": asin, "title": "测试耳机", "category": "耳机",
                "brand": "合成测试品牌", "pricing": 1, "options": {"颜色": ["黑色"]}}},
            available_actions={"has_search_bar": False, "clickables": ["buy now"]},
        )
        self.assertNotIn("selected_price", public)
        ledger = EvidenceLedger()
        ledger.ingest(public)
        decision = verify_purchase(parse_query("品类:耳机;预算:不超过100元"), ledger,
                                   intended_asin=asin, intended_options={"颜色": "黑色"})
        self.assertIn("price_unknown", decision.reasons)


if __name__ == "__main__":
    unittest.main()
