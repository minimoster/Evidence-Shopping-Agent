"""Untrusted intent proposals, source validation and separate acceptance states.

This legacy diagnostic path accepts only explicitly supplied inert fixtures.
The separate confirmed_intent/model_adapter path implements an opt-in LLM
provider with human confirmation. Schema/source validity never grants semantic
or purchase approval in either path.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import re
from typing import Protocol

from prototype.requirements import query_resource_issue
from .query_analysis import analyze_query
from .semantic_constraints import propose_constraints, accept_semantics

SCHEMA = "untrusted-intent-proposal-v1"
BUDGET_CLASSES = frozenset({"explicit_ceiling", "approximate_target", "soft_target",
    "nominal_target", "range", "absent", "absent_or_unrecognized", "ambiguous"})
_AMOUNT = re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,6})?")


class ProposalProvider(Protocol):
    """Query-only provider contract; not dispatched by legacy inspect_intent."""
    def propose(self, query: str) -> dict: ...


@dataclass(frozen=True)
class OfflineProposal:
    """Inert data for tests, never a callback or proof of NLU quality."""
    payload: object


def _sha(query):
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def _keys(value, names):
    return type(value) is dict and set(value) == set(names.split())


def _strings(value, *, maximum=8):
    return type(value) is list and len(value) <= maximum and all(type(v) is str and 0 < len(v) <= 256 for v in value)


def validate_proposal(query: str, proposal: object) -> tuple[str, ...]:
    """Check JSON contracts and exact source locations, not phrase entailment."""
    if type(query) is not str:
        raise TypeError("only the original plain query string is accepted")
    resource = query_resource_issue(query)
    if resource:
        return (resource,)
    if not _keys(proposal, "schema query_sha256 segments predicates budget"):
        return ("proposal_keys",)
    if type(proposal["schema"]) is not str or proposal["schema"] != SCHEMA or type(proposal["query_sha256"]) is not str or proposal["query_sha256"] != _sha(query):
        return ("proposal_identity",)
    segments, predicates = proposal["segments"], proposal["predicates"]
    if type(segments) is not list or len(segments) > 4096 or type(predicates) is not list or len(predicates) > 128:
        return ("proposal_size_or_type",)
    cursor = 0
    for s in segments:
        if not _keys(s, "start end text role") or type(s["start"]) is not int or type(s["end"]) is not int or type(s["text"]) is not str or type(s["role"]) is not str:
            return ("segment_type",)
        if s["role"] not in {"constraint", "context", "layout", "unresolved"}:
            return ("segment_role",)
        if s["start"] != cursor or not cursor < s["end"] <= len(query) or query[cursor:s["end"]] != s["text"]:
            return ("source_gap_overlap_or_mismatch",)
        if s["role"] == "layout" and any(not c.isspace() and c not in ";；,，" for c in s["text"]):
            return ("non_layout_text",)
        cursor = s["end"]
    if cursor != len(query):
        return ("source_incomplete",)

    linked = set()
    def references(refs, *, empty=False):
        if type(refs) is not list or len(refs) > 128 or (not refs and not empty):
            return False
        if any(type(i) is not int or not 0 <= i < len(segments) for i in refs) or len(set(refs)) != len(refs):
            return False
        if any(segments[i]["role"] not in {"constraint", "unresolved"} for i in refs):
            return False
        linked.update(refs)
        return True

    kinds = {"exact": {"eq"}, "negative": {"ne"}, "one_of": {"any"},
             "quantity": {"eq", "le", "lt", "ge", "gt"}, "interval": {"closed", "open"},
             "function": {"requires"}, "compatibility": {"requires"}, "unknown": {"unknown"}}
    for p in predicates:
        if not _keys(p, "kind key operator values unit strength source_spans"):
            return ("predicate_keys",)
        if any(type(p[k]) is not str for k in ("kind", "key", "operator", "strength")) or not 0 < len(p["key"]) <= 64:
            return ("predicate_type",)
        if p["kind"] not in kinds or p["operator"] not in kinds[p["kind"]] or p["strength"] not in {"hard", "soft", "uncertain"}:
            return ("predicate_contract",)
        if not _strings(p["values"]) or (p["unit"] is not None and (type(p["unit"]) is not str or not 0 < len(p["unit"]) <= 32)):
            return ("predicate_values",)
        count = len(p["values"])
        if p["kind"] in {"exact", "negative", "function", "compatibility"} and count != 1:
            return ("predicate_arity",)
        if p["kind"] == "one_of" and count < 2:
            return ("predicate_arity",)
        if p["kind"] in {"quantity", "interval"}:
            expected = 2 if p["kind"] == "quantity" else 4
            if count != expected or p["unit"] is None or any(not _AMOUNT.fullmatch(p["values"][i]) for i in range(0, count, 2)):
                return ("numeric_literal_or_unit_missing",)
            # Per-endpoint unit strings are preserved. Their meaning and any
            # conversion remain unverified; validation does not infer units.
        if not references(p["source_spans"]):
            return ("predicate_source_reference",)

    b = proposal["budget"]
    if not _keys(b, "classification amounts currency comparator approximate source_spans"):
        return ("budget_keys",)
    if type(b["classification"]) is not str or b["classification"] not in BUDGET_CLASSES:
        return ("budget_classification",)
    if not _strings(b["amounts"], maximum=2) or any(not _AMOUNT.fullmatch(v) or Decimal(v) <= 0 for v in b["amounts"]):
        return ("budget_amount",)
    if (b["currency"] is not None and (type(b["currency"]) is not str or b["currency"] not in {"CNY", "USD", "EUR"})) or (b["comparator"] is not None and (type(b["comparator"]) is not str or b["comparator"] not in {"le", "lt", "range", "target"})):
        return ("budget_currency_or_comparator",)
    if b["approximate"] is not None and type(b["approximate"]) is not bool:
        return ("budget_approximation_type",)
    if b["classification"] == "approximate_target" and b["approximate"] is not True:
        return ("approximate_target_contract",)
    absent = b["classification"] in {"absent", "absent_or_unrecognized"}
    if absent and (b["amounts"] or b["currency"] is not None or b["comparator"] is not None or b["source_spans"]):
        return ("absent_budget_has_values",)
    if b["classification"] == "explicit_ceiling" and (len(b["amounts"]) != 1 or b["currency"] is None or b["comparator"] not in {"lt", "le"} or b["approximate"] is not False):
        return ("ceiling_contract",)
    if b["classification"] == "range" and (len(b["amounts"]) != 2 or b["comparator"] != "range"):
        return ("range_contract",)
    if not references(b["source_spans"], empty=absent):
        return ("budget_source_reference",)
    if any(i not in linked for i, s in enumerate(segments) if s["role"] == "constraint"):
        return ("unreferenced_constraint_span",)
    return ()


def bounded_proposal(query: str) -> dict:
    """Legacy rule adapter, explicitly not a natural-language provider."""
    old = propose_constraints(query)
    segments = [{**c["span"], "role": "constraint" if c["node"] else "unresolved"} for c in old["clauses"]]
    segments += [{**s, "role": "layout"} for s in old["layout"]]
    segments.sort(key=lambda s: s["start"])
    by_start = {s["start"]: i for i, s in enumerate(segments)}
    predicates = [{**c["node"], "source_spans": [by_start[c["span"]["start"]]]}
                  for c in old["clauses"] if c["node"] and c["node"]["kind"] != "budget"]
    candidates = [p for p in analyze_query(query).predicates if p.kind in {"budget_ceiling", "budget_target"}]
    b = {"classification": "absent_or_unrecognized", "amounts": [], "currency": None,
         "comparator": None, "approximate": None, "source_spans": []}
    if len(candidates) > 1:
        b.update(classification="ambiguous", source_spans=[by_start[p.source_span.start] for p in candidates])
    elif candidates:
        p = candidates[0]
        kind = ("approximate_target" if p.approximate else "soft_target" if p.strength == "soft"
                else "explicit_ceiling" if p.strength == "hard" and p.kind == "budget_ceiling" else "nominal_target")
        b.update(classification=kind, amounts=[p.value], currency=p.currency,
                 comparator=p.operator, approximate=p.approximate, source_spans=[by_start[p.source_span.start]])
    return {"schema": SCHEMA, "query_sha256": _sha(query), "segments": segments,
            "predicates": predicates, "budget": b}


def inspect_intent(query: str, *, mode="disabled", fixture: OfflineProposal | None = None) -> dict:
    """Return an acceptance diagnostic, never an object usable by the buy gate.

    Model mode is unimplemented and rejected before any external dispatch. The
    fixture path handles inert data only; provider callbacks are never invoked.
    """
    if type(mode) is not str or mode not in {"disabled", "offline_fixture"}:
        raise ValueError("real proposal providers are not implemented or enabled")
    if (mode == "disabled" and fixture is not None) or (mode == "offline_fixture" and type(fixture) is not OfflineProposal):
        raise ValueError("offline proposals require explicit fixture mode and inert fixture data")
    reference = bounded_proposal(query)
    bounded = accept_semantics(query, propose_constraints(query))
    result = {"schema": SCHEMA, "mode": mode, "proposal_status": "disabled",
              "source_check": "not_run", "semantic_acceptance": "not_proposed",
              "issues": [], "proposed_budget_classification": None,
              "rule_budget_classification": reference["budget"]["classification"],
              "rule_budget_is_general_nlu": False, "bounded_rule_ready": bounded.ready,
              "proposal_model_calls": 0, "purchase_authorized": False}
    if mode == "disabled":
        return result
    errors = validate_proposal(query, fixture.payload)
    result.update(proposal_status="offline_fixture", source_check="invalid" if errors else "valid",
                  semantic_acceptance="rejected" if errors else "unverified", issues=list(errors))
    if errors:
        return result
    proposal = fixture.payload
    result["proposed_budget_classification"] = proposal["budget"]["classification"]
    if proposal == reference and bounded.ready:
        result["semantic_acceptance"] = "rule_verified"
    else:
        result["issues"].append("semantic_entailment_not_established")
        if proposal["budget"]["classification"] != "explicit_ceiling":
            result["issues"].append("hard_budget_not_established")
        if any(s["role"] == "unresolved" for s in proposal["segments"]) or any(p["strength"] == "uncertain" or p["kind"] == "unknown" for p in proposal["predicates"]):
            result["issues"].append("unresolved_intent")
        if len(result["issues"]) > 1:
            result["semantic_acceptance"] = "needs_clarification"
    return result
