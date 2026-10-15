from copy import deepcopy
import inspect
import json
import unittest
from unittest.mock import patch

from prototype import parse_query, verify_purchase
from shopping_demo.core import (DEFAULT_QUERY, Policy, PublicObservationError, ScriptedPolicy,
                                ShopAdapter, SyntheticShop, Task, ToolAction, public_observation,
                                replay_trace)


class DemoCoreTest(unittest.TestCase):
    def test_policy_protocol_is_public_query_and_observation_only(self):
        self.assertIsInstance(ScriptedPolicy(), Policy)
        self.assertEqual(list(inspect.signature(Policy.decide).parameters), ["self", "query", "observation"])
        self.assertEqual(list(inspect.signature(ScriptedPolicy.decide).parameters), ["self", "query", "observation"])
        self.assertIsInstance(SyntheticShop(), ShopAdapter)

    def test_success_has_real_gate_before_fixture_purchase(self):
        task = Task()
        with patch("shopping_demo.core.verify_purchase", wraps=verify_purchase) as gate:
            result = task.run()
        self.assertEqual(result["status"], "success")
        self.assertEqual(task.adapter.buy_calls, 1)
        self.assertEqual(gate.call_count, 1)
        self.assertEqual([e["action"]["tool"] for e in task.events if e["action"]], ["search", "open", "select", "buy"])
        self.assertTrue(task.events[-1]["gate"]["allowed"])
        self.assertEqual(task.events[-1]["gate"]["price"], "79.00")
        self.assertEqual(result["reason"], "synthetic_fixture_purchase_only")

    def test_budget_blocks_before_adapter_buy(self):
        task = Task(scenario="budget")
        self.assertEqual(task.run()["status"], "blocked")
        self.assertIn("over_budget", task.events[-1]["gate"]["reasons"])
        self.assertEqual(task.adapter.buy_calls, 0)

    def test_explicit_larger_budget_can_allow_current_synthetic_price(self):
        task = Task(DEFAULT_QUERY.replace("100元", "150元"), "budget")
        self.assertEqual(task.run()["status"], "success")

    def test_unknown_price_never_falls_back_to_catalog_minimum(self):
        task = Task(scenario="unknown_price")
        self.assertEqual(task.run()["status"], "blocked")
        self.assertIn("price_unknown", task.events[-1]["gate"]["reasons"])
        self.assertIsNone(task.events[-1]["gate"]["price"])
        self.assertEqual(task.adapter.buy_calls, 0)

    def test_variant_change_invalidates_previously_seen_price(self):
        task = Task(scenario="variant_price")
        task.step()
        task.step()
        self.assertEqual(str(task.ledger.current.price), "69.00")
        white_revision = task.ledger.current.revision
        task.step()
        self.assertGreater(task.ledger.current.revision, white_revision)
        self.assertEqual(task.observation["selected_options"], {"颜色": "黑色"})
        self.assertIsNone(task.ledger.current.price)
        task.step()
        self.assertEqual(task.status, "blocked")
        self.assertIn("price_unknown", task.events[-1]["gate"]["reasons"])
        self.assertEqual(task.adapter.buy_calls, 0)

    def test_buy_rechecks_current_observation_after_policy_proposal(self):
        class ChangedPrice(SyntheticShop):
            black_reads = 0
            def observe(self):
                obs = super().observe()
                if self.page == "product_detail" and self.selected == "黑色":
                    self.black_reads += 1
                    if self.black_reads >= 3:
                        obs["selected_price"] = "180.00"
                return obs
        task = Task(adapter=ChangedPrice())
        self.assertEqual(task.run()["status"], "blocked")
        self.assertIn("over_budget", task.events[-1]["gate"]["reasons"])
        self.assertEqual(task.adapter.buy_calls, 0)

    def test_failure_does_not_claim_success_or_leak_exception(self):
        task = Task(scenario="failure")
        self.assertEqual(task.run()["status"], "failure")
        self.assertEqual(task.adapter.buy_calls, 0)
        self.assertNotIn("synthetic_environment_unavailable", json.dumps(task.trace()))

    def test_max_steps_is_a_hard_tool_limit(self):
        class LoopPolicy:
            calls = 0
            def decide(self, query, observation):
                self.calls += 1
                return ToolAction("search", {"query": "耳机"})
        policy = LoopPolicy()
        task = Task(policy=policy, max_steps=2)
        self.assertEqual(task.run()["reason"], "step_limit_exceeded")
        self.assertEqual(task.steps, 2)
        self.assertEqual(policy.calls, 2)
        self.assertEqual(task.adapter.buy_calls, 0)

    def test_terminal_step_is_idempotent(self):
        task = Task()
        task.run()
        before = task.trace()
        task.step()
        task.run()
        self.assertEqual(task.trace(), before)
        self.assertEqual(task.adapter.buy_calls, 1)

    def test_illegal_tool_fails_closed_without_executing_or_logging_payload(self):
        class BadPolicy:
            def decide(self, query, observation):
                return ToolAction("arbitrary_url", {"url": "https://do-not-request.invalid"})
        task = Task(policy=BadPolicy())
        self.assertEqual(task.run()["reason"], "invalid_or_disallowed_tool")
        self.assertIsNone(task.events[-1]["action"])
        self.assertEqual(task.adapter.buy_calls, 0)

    def test_extra_buy_arguments_fail_closed(self):
        class BadPolicy:
            def decide(self, query, observation):
                return ToolAction("buy", {"asin": SyntheticShop.ASIN, "options": {}, "bypass": True})
        task = Task(policy=BadPolicy())
        self.assertEqual(task.run()["reason"], "invalid_or_disallowed_tool")
        self.assertEqual(task.adapter.buy_calls, 0)

    def test_policy_exception_fails_closed_without_secret_value(self):
        class BadPolicy:
            def decide(self, query, observation):
                raise RuntimeError("SECRET_VALUE_NEVER_PRINT")
        task = Task(policy=BadPolicy())
        self.assertEqual(task.run()["status"], "failure")
        self.assertNotIn("SECRET_VALUE_NEVER_PRINT", json.dumps(task.trace()))

    def test_policy_only_receives_a_detached_public_copy(self):
        class MutatingPolicy:
            def decide(self, query, observation):
                observation["actions"].append("fake")
                return ToolAction("finish", {"reason": "no_visible_candidate"})
        task = Task(policy=MutatingPolicy())
        task.step()
        self.assertNotIn("fake", task.observation["actions"])

    def test_hidden_fields_rejected_and_never_enter_policy_or_trace(self):
        for key in ("goal", "gold_target", "reward_detail", "secret", "hidden_note", "private", "access_token"):
            class Tainted(SyntheticShop):
                def observe(self):
                    return dict(super().observe(), **{key: "CANARY_DO_NOT_LEAK"})
            class NeverCalled:
                calls = 0
                def decide(self, query, observation):
                    self.calls += 1
                    raise AssertionError("must not see private data")
            with self.subTest(key=key):
                policy = NeverCalled()
                task = Task(adapter=Tainted(), policy=policy)
                self.assertEqual(task.run()["status"], "failure")
                self.assertEqual(policy.calls, 0)
                dumped = json.dumps(task.trace())
                self.assertNotIn("CANARY_DO_NOT_LEAK", dumped)
                self.assertNotIn(key, dumped)

    def test_unknown_nonpublic_values_are_not_forwarded(self):
        obs = dict(SyntheticShop().reset(), opaque_annotation={"note": "CANARY_NEVER_INCLUDE"})
        clean = public_observation(obs)
        self.assertNotIn("opaque_annotation", clean)
        self.assertNotIn("CANARY_NEVER_INCLUDE", json.dumps(clean))

    def test_nested_hidden_fields_and_cycles_rejected(self):
        obs = dict(SyntheticShop().reset(), unknown={"gold": "CANARY"})
        with self.assertRaises(PublicObservationError):
            public_observation(obs)
        obs = SyntheticShop().reset()
        obs["unknown"] = obs
        with self.assertRaises(PublicObservationError):
            public_observation(obs)

    def test_non_fixture_adapter_cannot_execute_buy_even_if_gate_allows(self):
        class NotFixture(SyntheticShop):
            fixture_mode = False
        task = Task(adapter=NotFixture())
        self.assertEqual(task.run()["reason"], "real_purchase_execution_disabled")
        self.assertEqual(task.adapter.buy_calls, 0)
        self.assertTrue(task.events[-1]["gate"]["allowed"])

    def test_unsupported_query_is_blocked_not_reinterpreted(self):
        task = Task("帮我买好一点的耳机，便宜一些")
        self.assertEqual(task.run()["status"], "blocked")
        self.assertEqual(task.reason, "query_not_supported")
        self.assertEqual(task.adapter.buy_calls, 0)

    def test_mismatched_brand_does_not_use_hidden_target(self):
        task = Task(DEFAULT_QUERY.replace("澄音", "不存在的品牌"))
        self.assertEqual(task.run()["reason"], "no_visible_candidate")

    def test_task_validation(self):
        for bad in (0, -1, 51, True, 1.1, "3"):
            with self.subTest(max_steps=bad), self.assertRaises(ValueError):
                Task(max_steps=bad)
        for query in ("", "x" * 1001, {}, None):
            with self.subTest(query=type(query).__name__), self.assertRaises(ValueError):
                Task(query)
        with self.assertRaises(ValueError):
            Task(scenario="not_a_scenario")

    def test_trace_roundtrip_rechecks_gate_for_all_scenarios(self):
        for scenario in ("success", "budget", "unknown_price", "variant_price", "failure"):
            with self.subTest(scenario=scenario):
                task = Task(scenario=scenario)
                task.run()
                result = replay_trace(json.loads(json.dumps(task.trace(), ensure_ascii=False)))
                self.assertTrue(result["valid"])
                self.assertEqual(result["gates_rechecked"], 0 if scenario == "failure" else 1)

    def test_tampered_gate_replay_rejected(self):
        task = Task(scenario="budget")
        task.run()
        trace = task.trace()
        trace["events"][-1]["gate"]["allowed"] = True
        with self.assertRaisesRegex(ValueError, "trace_gate_mismatch"):
            replay_trace(trace)

    def test_replay_rejects_hidden_fields(self):
        task = Task()
        task.run()
        trace = deepcopy(task.trace())
        trace["events"][0]["observation"]["secret"] = "CANARY"
        with self.assertRaises(ValueError):
            replay_trace(trace)


if __name__ == "__main__":
    unittest.main()
