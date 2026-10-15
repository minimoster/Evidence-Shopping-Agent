"""A bounded public-observation tool loop, using the actual prototype gate.

No model, network, task oracle, goal annotation, reward, or external catalog is
used. SyntheticShop is an original fixture, not a ShopSimulator reimplementation.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
import json
import re
import secrets
from typing import Protocol, runtime_checkable

from prototype import EvidenceLedger, parse_query, verify_purchase
from prototype.requirements import canonical_field, normalized_value

DISCLAIMER = "离线脚本演示 · 非 LLM · 不真实购物"
DEFAULT_QUERY = "品类:耳机;预算:不超过100元;品牌:澄音;颜色:黑色"
TRACE_VERSION = "offline-scripted-shopping-trace-v1"
SCENARIOS = {
    "success": "成功：合成商品 79 元，预算 100 元",
    "budget": "阻止：当前变体 129 元，超过默认预算",
    "unknown_price": "阻止：当前变体价格未知",
    "variant_price": "阻止：切换黑色后旧价失效，当前价未知",
    "failure": "失败：合成环境模拟不可用",
}
TERMINAL = {"success", "blocked", "failure"}
PUBLIC_VERSION = "shopping-observation-v2"
MAX_QUERY = 1000
_FORBIDDEN = {"goal", "goals", "gold", "reward", "answer", "target_asin", "oracle",
              "hidden", "secret", "secrets", "password", "token", "credentials", "private"}


class PublicObservationError(ValueError):
    """The adapter exposed non-public or malformed data; never echo its values."""


def _check_public_tree(value: object) -> None:
    stack = [value]
    seen: set[int] = set()
    count = 0
    while stack:
        node = stack.pop()
        if isinstance(node, (Mapping, list, tuple)):
            count += 1
            if count > 3000 or id(node) in seen:
                raise PublicObservationError("non_public_observation_rejected")
            seen.add(id(node))
            if isinstance(node, Mapping):
                for key, item in node.items():
                    if not isinstance(key, str):
                        raise PublicObservationError("non_public_observation_rejected")
                    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
                    words = set(re.split(r"[^a-z0-9]+", expanded.casefold()))
                    if key.startswith("_") or words & _FORBIDDEN:
                        raise PublicObservationError("non_public_observation_rejected")
                    stack.append(item)
            else:
                stack.extend(node)


def _text(value: object, limit: int = 500) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise PublicObservationError("malformed_public_observation")
    return value


def _text_map(value: object) -> dict:
    if not isinstance(value, Mapping) or len(value) > 12:
        raise PublicObservationError("malformed_public_observation")
    return {_text(k, 80): _text(v, 120) for k, v in value.items()}


def _product(value: object) -> dict:
    if not isinstance(value, Mapping):
        raise PublicObservationError("malformed_public_observation")
    product = {key: _text(value.get(key)) for key in ("asin", "title", "brand", "category")}
    attributes = value.get("key_attributes", [])
    if not isinstance(attributes, list) or len(attributes) > 40:
        raise PublicObservationError("malformed_public_observation")
    product["key_attributes"] = [_text(x) for x in attributes]
    # A catalog price is display-only. The gate requires selected_price for variants.
    price = value.get("price")
    if price is not None and (isinstance(price, bool) or not isinstance(price, (str, int, float))):
        raise PublicObservationError("malformed_public_observation")
    if isinstance(price, str):
        _text(price, 80)
    product["price"] = price
    return product


def public_observation(raw: object) -> dict:
    """Copy an explicit schema, never forward raw info/annotations/debug fields.

    Forbidden-key taint causes failure rather than merely hiding it from a policy.
    Unknown benign fields are discarded. Error messages do not include raw values.
    """
    _check_public_tree(raw)
    if not isinstance(raw, Mapping) or raw.get("observation_version") != PUBLIC_VERSION:
        raise PublicObservationError("malformed_public_observation")
    page = raw.get("page_type")
    if page not in {"search_home", "search_results", "product_detail", "information_subpage", "terminal"}:
        raise PublicObservationError("malformed_public_observation")
    if not isinstance(raw.get("search_available"), bool):
        raise PublicObservationError("malformed_public_observation")
    actions = raw.get("actions")
    if not isinstance(actions, list) or len(actions) > 60:
        raise PublicObservationError("malformed_public_observation")
    out = {"observation_version": PUBLIC_VERSION, "page_type": page,
           "search_available": raw["search_available"], "actions": [_text(x, 150) for x in actions]}
    if page == "search_results":
        products = raw.get("products", [])
        if not isinstance(products, list) or len(products) > 30:
            raise PublicObservationError("malformed_public_observation")
        out["products"] = [_product(p) for p in products]
    if page in {"product_detail", "information_subpage"}:
        out["product"] = _product(raw.get("product"))
        out["selected_options"] = _text_map(raw.get("selected_options"))
        available = raw.get("available_options")
        if not isinstance(available, Mapping) or len(available) > 12:
            raise PublicObservationError("malformed_public_observation")
        out["available_options"] = {}
        for key, values in available.items():
            if not isinstance(values, list) or len(values) > 30:
                raise PublicObservationError("malformed_public_observation")
            out["available_options"][_text(key, 80)] = [_text(x, 120) for x in values]
        if "selected_price" in raw:
            price = raw["selected_price"]
            if price is not None and (isinstance(price, bool) or not isinstance(price, (str, int, float))):
                raise PublicObservationError("malformed_public_observation")
            if isinstance(price, str):
                _text(price, 80)
            out["selected_price"] = price
    if page == "terminal":
        out["outcome"] = _text(raw.get("outcome", ""), 80)
    # Ensures JSON-safe finite numbers before the observation reaches policy/trace.
    try:
        json.dumps(out, allow_nan=False)
    except (ValueError, TypeError):
        raise PublicObservationError("malformed_public_observation") from None
    return out


@dataclass(frozen=True)
class ToolAction:
    tool: str
    arguments: Mapping = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"tool": self.tool, "arguments": deepcopy(dict(self.arguments))}


@runtime_checkable
class Policy(Protocol):
    """The sole policy API: original user query and sanitized public observation.

    Implementations must not accept task/gold/reward/info arguments. The default
    implementation below is a deterministic script, not an LLM or trained agent.
    """

    def decide(self, query: str, observation: Mapping) -> ToolAction: ...


@runtime_checkable
class ShopAdapter(Protocol):
    """Future adapter boundary. An implementation is NOT included for real shops.

    reset/observe/execute must return only the documented public observation.
    Never return a simulator's full (observation, reward, done, info) tuple here.
    A non-fixture adapter cannot execute buy in this offline runner.
    """
    fixture_mode: bool

    def reset(self) -> Mapping: ...
    def observe(self) -> Mapping: ...
    def execute(self, action: ToolAction) -> Mapping: ...


class ScriptedPolicy:
    """Explicit ScriptedPolicy: no LLM, no learning, no hidden target selection.

    Follows a visible candidate, selects an exact requested visible option, and
    proposes buy. It deliberately leaves final constraint checking to the gate.
    """

    def decide(self, query: str, observation: Mapping) -> ToolAction:
        requirements = parse_query(query)
        if not requirements.ready:
            return ToolAction("finish", {"reason": "query_not_supported"})
        page = observation["page_type"]
        if page == "search_home":
            category = next((s.value for s in requirements.specs if s.key == "category"), "")
            return ToolAction("search", {"query": category or query})
        if page == "search_results":
            products = observation.get("products", [])
            for product in products:
                if all(normalized_value(product.get(spec.key, "")) == normalized_value(spec.value)
                       for spec in requirements.specs if spec.key in {"brand", "title", "category"}):
                    return ToolAction("open", {"asin": product["asin"]})
            return ToolAction("finish", {"reason": "no_visible_candidate"})
        if page == "product_detail":
            for axis, values in observation["available_options"].items():
                expected = next((s.value for s in requirements.specs if s.key == canonical_field(axis)), None)
                if expected is not None:
                    match = next((v for v in values if normalized_value(v) == normalized_value(expected)), None)
                    if match is None:
                        return ToolAction("finish", {"reason": "requested_option_unavailable"})
                    if observation["selected_options"].get(axis) != match:
                        return ToolAction("select", {"axis": axis, "value": match})
            return ToolAction("buy", {"asin": observation["product"]["asin"],
                                      "options": dict(observation["selected_options"])})
        return ToolAction("finish", {"reason": "no_supported_next_action"})


class SyntheticShop:
    """Tiny original catalog with synthetic names, prices, and descriptions.

    Nothing is fetched or copyrighted catalog data bundled. execute('buy') only
    changes this in-memory fixture. It has no payment/account/network capability.
    """
    fixture_mode = True
    ASIN = "000000000101"

    def __init__(self, scenario: str = "success") -> None:
        if scenario not in SCENARIOS:
            raise ValueError("unknown_scenario")
        self.scenario = scenario
        self.page = "search_home"
        self.selected = "白色"
        self.buy_calls = 0
        self.search_term = ""

    @staticmethod
    def _base(page: str, actions: list[str], search: bool = False) -> dict:
        return {"observation_version": PUBLIC_VERSION, "page_type": page,
                "search_available": search, "actions": actions}

    def reset(self) -> Mapping:
        self.page, self.selected, self.buy_calls, self.search_term = "search_home", "白色", 0, ""
        return self.observe()

    def _product(self) -> dict:
        return {"asin": self.ASIN, "title": "澄音练习耳机 A1（合成）", "brand": "澄音",
                "category": "耳机", "price": "69 to 129", "key_attributes": ["型号:A1", "材质:树脂"]}

    def observe(self) -> Mapping:
        if self.page == "search_home":
            return self._base(self.page, ["search"], True)
        if self.page == "search_results":
            obs = self._base(self.page, [self.ASIN, "back to search"], True)
            obs["products"] = [self._product()] if "耳机" in self.search_term else []
            return obs
        if self.page == "terminal":
            return dict(self._base(self.page, []), outcome="fixture_purchase")
        obs = dict(self._base("product_detail", ["buy now", "白色", "黑色", "back to search"]),
                   product=self._product(), selected_options={"颜色": self.selected},
                   available_options={"颜色": ["白色", "黑色"]})
        if self.scenario == "unknown_price" or (self.scenario == "variant_price" and self.selected == "黑色"):
            obs["selected_price"] = None
        else:
            obs["selected_price"] = "129.00" if self.scenario == "budget" else ("79.00" if self.selected == "黑色" else "69.00")
        return obs

    def execute(self, action: ToolAction) -> Mapping:
        if self.scenario == "failure":
            raise RuntimeError("synthetic_environment_unavailable")
        args = action.arguments
        if action.tool == "search" and self.page in {"search_home", "search_results"}:
            self.search_term, self.page = args["query"], "search_results"
        elif action.tool == "open" and self.page == "search_results" and args["asin"] == self.ASIN:
            self.page = "product_detail"
        elif action.tool == "select" and self.page == "product_detail" and args["axis"] == "颜色" and args["value"] in {"白色", "黑色"}:
            self.selected = args["value"]
        elif action.tool == "buy" and self.page == "product_detail" and args["asin"] == self.ASIN and dict(args["options"]) == {"颜色": self.selected}:
            self.buy_calls += 1
            self.page = "terminal"
        else:
            raise ValueError("tool_not_available_in_fixture_state")
        return self.observe()


def _valid_action(action: object) -> bool:
    if not isinstance(action, ToolAction) or not isinstance(action.arguments, Mapping):
        return False
    args = action.arguments
    _check_public_tree(args)
    if action.tool == "search":
        return set(args) == {"query"} and isinstance(args["query"], str) and 0 < len(args["query"]) <= MAX_QUERY
    if action.tool == "open":
        return set(args) == {"asin"} and isinstance(args["asin"], str) and re.fullmatch(r"\d{8,12}", args["asin"]) is not None
    if action.tool == "select":
        return set(args) == {"axis", "value"} and all(isinstance(x, str) and 0 < len(x) <= 120 for x in args.values())
    if action.tool == "buy":
        return set(args) == {"asin", "options"} and isinstance(args["asin"], str) and re.fullmatch(r"\d{8,12}", args["asin"]) is not None and isinstance(args["options"], Mapping) and len(args["options"]) <= 12 and all(isinstance(k, str) and isinstance(v, str) and len(k) <= 80 and len(v) <= 120 for k, v in args["options"].items())
    if action.tool == "finish":
        return set(args) == {"reason"} and args["reason"] in {"query_not_supported", "no_visible_candidate", "requested_option_unavailable", "no_supported_next_action"}
    return False


class Task:
    """One bounded task. Every proposed buy passes the actual current gate."""

    def __init__(self, query: str = DEFAULT_QUERY, scenario: str = "success", *,
                 policy: Policy | None = None, adapter: ShopAdapter | None = None, max_steps: int = 12):
        if not isinstance(query, str) or not 0 < len(query) <= MAX_QUERY:
            raise ValueError("query_length_must_be_1_to_1000")
        if type(max_steps) is not int or not 1 <= max_steps <= 50:
            raise ValueError("max_steps_must_be_1_to_50")
        if scenario not in SCENARIOS:
            raise ValueError("unknown_scenario")
        self.task_id, self.trace_id = secrets.token_hex(12), secrets.token_hex(12)
        self.query, self.scenario, self.max_steps = query, scenario, max_steps
        self.requirements = parse_query(query)
        self.policy = policy if policy is not None else ScriptedPolicy()
        self.adapter = adapter if adapter is not None else SyntheticShop(scenario)
        self.ledger, self.events = EvidenceLedger(), []
        self.status, self.reason, self.steps = "ready", "ready", 0
        self.observation: dict = {}
        try:
            self._ingest(self.adapter.reset())
        except Exception:
            self._fail("initial_observation_unavailable")
        self._record(None, None, None)

    def _ingest(self, raw: object) -> dict:
        obs = public_observation(raw)
        self.ledger.ingest(obs)
        self.observation = obs
        return obs

    def _fail(self, reason: str) -> None:
        self.status, self.reason = "failure", reason

    def _record(self, action: ToolAction | None, before: dict | None, decision: dict | None) -> None:
        self.events.append({"index": len(self.events), "step": self.steps,
                            "action": action.to_dict() if action else None,
                            "before": deepcopy(before), "observation": deepcopy(self.observation),
                            "gate": deepcopy(decision), "status": self.status, "reason": self.reason})

    def step(self) -> dict:
        if self.status in TERMINAL:
            return self.state()
        if self.steps >= self.max_steps:
            self._fail("step_limit_exceeded")
            self._record(None, None, None)
            return self.state()
        self.steps += 1
        self.status, self.reason = "running", "step_completed"
        before, action, decision = None, None, None
        try:
            before = deepcopy(self._ingest(self.adapter.observe()))
            proposed = self.policy.decide(self.query, deepcopy(before))
            if not _valid_action(proposed):
                self._fail("invalid_or_disallowed_tool")
            else:
                # Copy before validation/use so a policy cannot mutate the args later.
                action = ToolAction(proposed.tool, deepcopy(dict(proposed.arguments)))
                if action.tool == "finish":
                    self.status, self.reason = "blocked", action.arguments["reason"]
                elif action.tool == "buy":
                    # Fresh read after proposal: an old variant/price cannot authorize buy.
                    before = deepcopy(self._ingest(self.adapter.observe()))
                    proof = verify_purchase(self.requirements, self.ledger,
                                            intended_asin=action.arguments["asin"],
                                            intended_options=action.arguments["options"])
                    decision = proof.to_dict()
                    if not proof.allowed or not self.ledger.decision_is_current(proof, self.requirements):
                        self.status, self.reason = "blocked", "purchase_gate_blocked"
                    elif self.adapter.fixture_mode is not True:
                        self._fail("real_purchase_execution_disabled")
                    else:
                        self._ingest(self.adapter.execute(action))
                        if self.observation.get("page_type") == "terminal" and self.observation.get("outcome") == "fixture_purchase":
                            self.status, self.reason = "success", "synthetic_fixture_purchase_only"
                        else:
                            self._fail("fixture_purchase_not_confirmed")
                else:
                    self._ingest(self.adapter.execute(action))
        except PublicObservationError:
            self._fail("non_public_or_malformed_observation_rejected")
        except Exception:
            # Never log exception values, which might contain adapter secrets.
            self._fail("policy_or_environment_error")
        self._record(action, before, decision)
        return self.state()

    def run(self) -> dict:
        while self.status not in TERMINAL:
            self.step()
        return self.state()

    def state(self) -> dict:
        return {"task_id": self.task_id, "trace_id": self.trace_id, "scenario": self.scenario,
                "policy": "ScriptedPolicy (non-LLM)" if isinstance(self.policy, ScriptedPolicy) else "custom_policy",
                "disclaimer": DISCLAIMER, "query": self.query, "status": self.status,
                "reason": self.reason, "steps": self.steps, "max_steps": self.max_steps,
                "requirements": self.requirements.to_dict(), "observation": deepcopy(self.observation),
                "last_event": deepcopy(self.events[-1]) if self.events else None,
                "trace_length": len(self.events)}

    def trace(self) -> dict:
        return {"trace_version": TRACE_VERSION, "disclaimer": DISCLAIMER, "policy": "ScriptedPolicy (non-LLM)" if isinstance(self.policy, ScriptedPolicy) else "custom_policy",
                "task_id": self.task_id, "trace_id": self.trace_id, "query": self.query,
                "scenario": self.scenario, "max_steps": self.max_steps,
                "status": self.status, "events": deepcopy(self.events)}


def replay_trace(trace: object) -> dict:
    """Validate/render a public JSON trace and re-evaluate each recorded gate.

    This is deterministic evidence replay, not rerunning an agent or live shop.
    Revisions in recomputed proofs are local to replay; allow/reasons must agree.
    """
    if not isinstance(trace, dict) or trace.get("trace_version") != TRACE_VERSION:
        raise ValueError("unsupported_trace_version")
    _check_public_tree(trace)
    query = trace.get("query")
    if not isinstance(query, str) or not 0 < len(query) <= MAX_QUERY:
        raise ValueError("invalid_trace_query")
    events = trace.get("events")
    if not isinstance(events, list) or not 1 <= len(events) <= 52:
        raise ValueError("invalid_trace_events")
    gates = 0
    for index, event in enumerate(events):
        if not isinstance(event, dict) or event.get("index") != index:
            raise ValueError("invalid_trace_event_order")
        if event.get("observation"):
            if public_observation(event["observation"]) != event["observation"]:
                raise ValueError("trace_contains_non_public_fields")
        if event.get("before"):
            if public_observation(event["before"]) != event["before"]:
                raise ValueError("trace_contains_non_public_fields")
        action = event.get("action")
        if action is not None:
            if not isinstance(action, dict) or set(action) != {"tool", "arguments"}:
                raise ValueError("invalid_trace_action")
            tool = ToolAction(action["tool"], action["arguments"])
            if not _valid_action(tool):
                raise ValueError("invalid_trace_action")
            if tool.tool == "buy":
                if not event.get("before") or not isinstance(event.get("gate"), dict):
                    raise ValueError("trace_buy_without_gate")
                ledger = EvidenceLedger()
                ledger.ingest(event["before"])
                proof = verify_purchase(parse_query(query), ledger, intended_asin=tool.arguments["asin"],
                                        intended_options=tool.arguments["options"])
                if proof.allowed != event["gate"].get("allowed") or list(proof.reasons) != event["gate"].get("reasons"):
                    raise ValueError("trace_gate_mismatch")
                gates += 1
    return {"valid": True, "events": len(events), "gates_rechecked": gates,
            "status": trace.get("status"), "disclaimer": DISCLAIMER,
            "limitation": "Public evidence replay, not authenticity proof or simulator success evidence."}
