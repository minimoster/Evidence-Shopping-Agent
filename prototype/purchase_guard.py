"""Public-observation-only, fail-closed evidence ledger and pre-purchase gate.

This module does not select products, execute an action, access task/reward data,
or certify simulator success. Public snapshots and decisions are revision-bound.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import re

from .requirements import QueryRequirements, canonical_field, normalized_value, parse_query

OBSERVATION_VERSION = "shopping-observation-v2"
PRODUCT_ID = re.compile(r"\d{8,12}\Z")
_FORBIDDEN = {"goal", "goals", "reward", "reward_detail", "answer", "target_asin", "gold", "oracle"}


@dataclass(frozen=True)
class Evidence:
    key: str
    value: str
    source_path: str
    asin: str
    variant: tuple[tuple[str, str], ...]
    revision: int

    def to_dict(self) -> dict:
        return {"key": self.key, "value": self.value, "source_path": self.source_path,
                "asin": self.asin, "variant": dict(self.variant), "revision": self.revision}


@dataclass(frozen=True)
class PublicSnapshot:
    revision: int
    page_type: str
    asin: str | None
    variant: tuple[tuple[str, str], ...]
    available_axes: tuple[str, ...]
    price: Decimal | None
    price_path: str | None
    actions: tuple[str, ...]
    facts: tuple[Evidence, ...]
    issues: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"revision": self.revision, "page_type": self.page_type, "asin": self.asin,
                "variant": dict(self.variant), "available_axes": list(self.available_axes),
                "price": str(self.price) if self.price is not None else None,
                "price_path": self.price_path, "actions": list(self.actions),
                "facts": [fact.to_dict() for fact in self.facts], "issues": list(self.issues)}


@dataclass(frozen=True)
class PurchaseDecision:
    allowed: bool
    reasons: tuple[str, ...]
    revision: int
    query_digest: str
    asin: str | None
    variant: tuple[tuple[str, str], ...]
    price: Decimal | None
    budget: Decimal | None
    evidence: tuple[Evidence, ...]

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "reasons": list(self.reasons), "revision": self.revision,
                "query_digest": self.query_digest, "asin": self.asin, "variant": dict(self.variant),
                "price": str(self.price) if self.price is not None else None,
                "budget": str(self.budget) if self.budget is not None else None,
                "evidence": [fact.to_dict() for fact in self.evidence]}


def _hidden_paths(value: object) -> tuple[str, ...]:
    """Reject taint by key names, without using hidden values as evidence.

    Unknown fields otherwise never enter the allowlisted proof. Traverse with a
    bound so non-JSON cycles/overlarge objects cannot preserve a prior approval.
    """
    stack = [(value, "$")]
    visited: set[int] = set()
    paths = []
    count = 0
    while stack:
        node, path = stack.pop()
        if not isinstance(node, (Mapping, list, tuple)):
            continue
        identity = id(node)
        if identity in visited:
            paths.append("non_json_shared_or_cyclic_container")
            continue
        visited.add(identity)
        count += 1
        if count > 10000:
            paths.append("observation_too_complex")
            break
        if isinstance(node, Mapping):
            for key, child in node.items():
                key_text = str(key).casefold()
                child_path = path + "." + str(key)
                if key_text in _FORBIDDEN or key_text.startswith(("gold_", "reward_", "goal_")):
                    paths.append(child_path)
                else:
                    stack.append((child, child_path))
        else:
            stack.extend((child, f"{path}[{index}]") for index, child in enumerate(node))
    return tuple(paths)


def _price(value: object, *, singleton_list: bool = False) -> Decimal | None:
    if singleton_list and isinstance(value, list) and len(value) == 1:
        value = value[0]
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    if isinstance(value, str) and not re.fullmatch(r"\d+(?:\.\d+)?", value.strip()):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and number >= 0 else None


def _options(value: object) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    if not isinstance(value, Mapping):
        return (), ("selected_options_not_object",)
    output = {}
    issues = []
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str) or not raw_key.strip() or not isinstance(raw_value, str) or not raw_value.strip():
            issues.append("invalid_selected_option")
            continue
        key = canonical_field(raw_key)
        if key in output:
            issues.append("selected_axis_collision:" + key)
        output[key] = normalized_value(raw_value)
    return tuple(sorted(output.items())), tuple(issues)


class EvidenceLedger:
    """Append-only audit; only the newest observation is active purchase proof.

    Each ingest atomically replaces the active snapshot, even on invalid input.
    No old price, action or specification is copied into a new revision.
    The module accepts native public states, not full reset()/step() info objects.
    """
    def __init__(self) -> None:
        self._history: list[PublicSnapshot] = []

    @property
    def current(self) -> PublicSnapshot | None:
        return self._history[-1] if self._history else None

    @property
    def history(self) -> tuple[PublicSnapshot, ...]:
        return tuple(self._history)

    def ingest(self, observation: Mapping) -> PublicSnapshot:
        revision = len(self._history) + 1
        issues: list[str] = []
        page_type = "unknown"
        asin = None
        variant: tuple[tuple[str, str], ...] = ()
        available: dict[str, set[str]] = {}
        facts: list[Evidence] = []
        actions: tuple[str, ...] = ()
        price = None
        price_path = None
        if not isinstance(observation, Mapping):
            issues.append("observation_not_object")
        else:
            taint = _hidden_paths(observation)
            if taint:
                issues.append("forbidden_or_non_public_payload")
            elif observation.get("observation_version") != OBSERVATION_VERSION:
                issues.append("unsupported_observation_version")
            else:
                page_type = observation.get("page_type")
                if not isinstance(page_type, str) or page_type not in {
                    "search_home", "search_results", "product_detail", "information_subpage", "terminal"
                }:
                    issues.append("unsupported_page_type")
                    page_type = "unknown"
                raw_actions = observation.get("actions")
                if not isinstance(raw_actions, list) or any(not isinstance(item, str) for item in raw_actions):
                    issues.append("actions_not_string_list")
                else:
                    actions = tuple(raw_actions)
                if not isinstance(observation.get("search_available"), bool):
                    issues.append("search_available_not_boolean")
                if page_type in {"product_detail", "information_subpage"}:
                    product = observation.get("product")
                    if not isinstance(product, Mapping):
                        issues.append("product_not_object")
                        product = {}
                    raw_asin = product.get("asin")
                    if not isinstance(raw_asin, str) or not PRODUCT_ID.fullmatch(raw_asin):
                        issues.append("invalid_product_asin")
                    else:
                        asin = raw_asin
                    variant, selection_issues = _options(observation.get("selected_options"))
                    issues.extend(selection_issues)
                    raw_available = observation.get("available_options")
                    if not isinstance(raw_available, Mapping):
                        issues.append("available_options_not_object")
                    else:
                        for raw_axis, values in raw_available.items():
                            if not isinstance(raw_axis, str) or not raw_axis.strip():
                                issues.append("invalid_available_axis")
                                continue
                            axis = canonical_field(raw_axis)
                            if axis in available:
                                issues.append("available_axis_collision:" + axis)
                            if not isinstance(values, list) or not values or any(
                                not isinstance(value, str) or not value.strip() for value in values
                            ):
                                issues.append("invalid_available_values:" + axis)
                                available[axis] = set()
                                continue
                            normalized = [normalized_value(value) for value in values]
                            if len(set(normalized)) != len(normalized):
                                issues.append("available_value_collision:" + axis)
                            available[axis] = set(normalized)
                    selection = dict(variant)
                    if set(selection) != set(available):
                        issues.append("selection_incomplete_or_extra_axes")
                    for axis, value in variant:
                        if value not in available.get(axis, set()):
                            issues.append("selected_value_not_available:" + axis)
                    if "selected_price" in observation:
                        price = _price(observation["selected_price"])
                        price_path = "$.selected_price"
                    elif not available and not variant and isinstance(raw_available, Mapping):
                        # Native no-option catalog price can be scalar/singleton,
                        # never a minimum from a range or multi-variant price list.
                        price = _price(product.get("price"), singleton_list=True)
                        price_path = "$.product.price"
                    if price is None:
                        issues.append("current_price_unknown")
                    if asin is not None:
                        for key in ("title", "brand", "category"):
                            value = product.get(key)
                            if not isinstance(value, str):
                                issues.append("invalid_product_text:" + key)
                            elif value.strip():
                                facts.append(Evidence(key, value, "$.product." + key, asin, variant, revision))
                        attributes = product.get("key_attributes")
                        if not isinstance(attributes, list) or any(not isinstance(value, str) for value in attributes):
                            issues.append("key_attributes_not_string_list")
                        else:
                            for index, value in enumerate(attributes):
                                path = f"$.product.key_attributes[{index}]"
                                facts.append(Evidence("attribute", value, path, asin, variant, revision))
                                match = re.fullmatch(r"\s*([^:：]+)\s*[:：]\s*(.+?)\s*", value)
                                if match:
                                    key = canonical_field(match.group(1))
                                    # Structured attribute labels are exact data,
                                    # not substring/compatibility/function inference.
                                    if not key.startswith("raw:") and key not in {"title", "brand", "category", "attribute"}:
                                        facts.append(Evidence("attribute:" + key, match.group(2), path, asin, variant, revision))
                        for raw_axis, value in (observation["selected_options"].items() if isinstance(observation.get("selected_options"), Mapping) else ()):
                            if isinstance(raw_axis, str) and isinstance(value, str):
                                facts.append(Evidence("option:" + canonical_field(raw_axis), value,
                                    "$.selected_options[" + repr(raw_axis) + "]", asin, variant, revision))
        snapshot = PublicSnapshot(revision, page_type, asin, variant, tuple(sorted(available)),
                                  price, price_path, actions, tuple(facts), tuple(dict.fromkeys(issues)))
        self._history.append(snapshot)
        return snapshot

    def decision_is_current(self, decision: PurchaseDecision, requirements: QueryRequirements) -> bool:
        """Freshness helper, not execution authorization or a transactional lock."""
        snapshot = self.current
        return bool(snapshot and decision.allowed and decision.revision == snapshot.revision
                    and decision.asin == snapshot.asin and decision.variant == snapshot.variant
                    and decision.price == snapshot.price
                    and decision.query_digest == _query_digest(requirements))


def _query_digest(requirements: QueryRequirements) -> str:
    return hashlib.sha256(requirements.query.encode("utf-8")).hexdigest()


def snapshot_preconditions(snapshot: PublicSnapshot, intended_asin: str,
                           intended_options: Mapping) -> tuple[str, ...]:
    """Shared current-product checks; no query interpretation or authorization."""
    reasons = ["observation:" + issue for issue in snapshot.issues]
    if snapshot.page_type != "product_detail":
        reasons.append("not_current_product_detail")
    if "buy now" not in {action.casefold() for action in snapshot.actions}:
        reasons.append("buy_action_not_currently_visible")
    if intended_asin != snapshot.asin:
        reasons.append("intended_asin_mismatch")
    intended_variant, option_issues = _options(intended_options)
    if option_issues or intended_variant != snapshot.variant:
        reasons.append("intended_variant_mismatch")
    if snapshot.price is None:
        reasons.append("price_unknown")
    return tuple(reasons)


def verify_purchase(requirements: QueryRequirements, ledger: EvidenceLedger, *,
                    intended_asin: str, intended_options: Mapping) -> PurchaseDecision:
    """Gate a concrete intended ASIN/variant against only latest public evidence.

    The caller must pass parse_query(original_user_query), not annotations, and
    the exact current native option map. No goal/reward/gold argument exists.
    """
    if not isinstance(requirements, QueryRequirements):
        raise TypeError("requirements must be produced by parse_query")
    if not isinstance(ledger, EvidenceLedger):
        raise TypeError("ledger must be an EvidenceLedger")
    snapshot = ledger.current
    reasons = []
    matched = []
    maximum = requirements.budget.maximum if requirements.budget else None
    if requirements != parse_query(requirements.query):
        reasons.append("query:compiled_requirements_mismatch")
    if not requirements.ready:
        reasons.extend("query:" + issue for issue in requirements.issues)
        if not reasons:
            reasons.append("query:requirements_not_ready")
    if snapshot is None:
        reasons.append("no_public_observation")
        return PurchaseDecision(False, tuple(reasons), 0, _query_digest(requirements), None, (), None, maximum, ())
    reasons.extend(snapshot_preconditions(snapshot, intended_asin, intended_options))
    if requirements.budget is None:
        reasons.append("budget_unknown")
    elif requirements.budget.currency != "CNY":
        reasons.append("unsupported_currency")
    elif snapshot.price is not None:
        if (snapshot.price > maximum or (not requirements.budget.inclusive and snapshot.price == maximum)):
            reasons.append("over_budget")
    for spec in requirements.specs:
        if spec.key in {"title", "brand", "category", "attribute"}:
            key = spec.key
        elif spec.key in snapshot.available_axes:
            key = "option:" + spec.key
        else:
            key = "attribute:" + spec.key
        candidates = [fact for fact in snapshot.facts if fact.key == key
                      and fact.asin == snapshot.asin and fact.variant == snapshot.variant
                      and fact.revision == snapshot.revision]
        expected = normalized_value(spec.value)
        exact = [fact for fact in candidates if normalized_value(fact.value) == expected]
        # Multiple conflicting labeled claims are not proof, even if one matches.
        conflicting = spec.key != "attribute" and len({normalized_value(f.value) for f in candidates}) > 1
        if exact and not conflicting:
            matched.extend(exact)
        else:
            reasons.append("spec_unproven:" + spec.key)
    return PurchaseDecision(not reasons, tuple(dict.fromkeys(reasons)), snapshot.revision,
                            _query_digest(requirements), snapshot.asin, snapshot.variant,
                            snapshot.price, maximum, tuple(matched))
