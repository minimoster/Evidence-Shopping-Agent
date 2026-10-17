"""Bounded semantic acceptance and current-public-evidence review, without actions.

This opt-in API does not replace the frozen A/B/C runner or canonical v3 parser.
Proposals are untrusted. Both acceptance and verification independently compile
the original query. No model, task metadata, catalog or reward is parser input.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, localcontext
import hashlib
import json
import re

from prototype.requirements import (
    FIELD_ALIASES, natural_value_is_ambiguous, normalized_value, parse_query,
    query_resource_issue,
)
from prototype.purchase_guard import EvidenceLedger, snapshot_preconditions
from .query_analysis import analyze_query

VERSION = "bounded-semantics-v1"
_NUMBER = r"[0-9]{1,12}(?:\.[0-9]{1,6})?"
_UNIT = r"mL|ml|毫升|L|升"
_MEASURE = re.compile(r"(" + _NUMBER + r")\s*(" + _UNIT + r")")
_CAPACITY = re.compile(r"容量\s*(至少|不低于|大于|至多|不超过|小于|为)\s*(" + _NUMBER + r")\s*(" + _UNIT + r")。?")
_INTERVAL = re.compile(r"容量在\s*(" + _NUMBER + r")\s*(" + _UNIT + r")\s*到\s*(" + _NUMBER + r")\s*(" + _UNIT + r")\s*之间（含两端）。?")
_LABELS = "|".join(re.escape(k) for k in sorted(FIELD_ALIASES, key=len, reverse=True) if not k.isascii())
_CHOICE = re.compile(r"(" + _LABELS + r")(?:必须为|必须是|是|为)(.+?)。?")
_NEGATION = re.compile(r"(颜色|颜色分类|尺码|套餐)(?:不是|不得为|不能为|不要)(.+?)。?")
_OPS = {"至少": "ge", "不低于": "ge", "大于": "gt", "至多": "le", "不超过": "le", "小于": "lt", "为": "eq"}


def _digest(query):
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def _span(start, end, query):
    return {"start": start, "end": end, "text": query[start:end]}


def _node(kind, key, operator, values, *, unit=None, strength="hard"):
    return {"kind": kind, "key": key, "operator": operator, "values": values,
            "unit": unit, "strength": strength}


def _ml(amount, unit):
    # This grammar bounds digits; ambient application Decimal precision must not
    # round a value across a purchase boundary.
    with localcontext() as context:
        context.prec = 32
        return Decimal(amount) * (1000 if unit in {"L", "升"} else 1)


def _literal(text):
    return bool(text and len(text) <= 120 and not natural_value_is_ambiguous(text))


def _parse_clause(text):
    """Return a predicate or an explicit non-acceptance; never trim free prose."""
    interval = _INTERVAL.fullmatch(text)
    if interval:
        low, low_unit, high, high_unit = interval.groups()
        if _ml(low, low_unit) > _ml(high, high_unit):
            return None, "needs_clarification", "reversed_interval"
        return _node("interval", "capacity", "closed", [low, low_unit, high, high_unit], unit="mL"), "supported", None
    quantity = _CAPACITY.fullmatch(text)
    if quantity:
        op, number, unit = quantity.groups()
        return _node("quantity", "capacity", _OPS[op], [number, unit], unit="mL"), "supported", None
    negative = _NEGATION.fullmatch(text)
    if negative and _literal(negative[2]):
        return _node("negative", FIELD_ALIASES[negative[1]], "ne", [negative[2]]), "supported", None
    choice = _CHOICE.fullmatch(text)
    if choice and "或" in choice[2]:
        values = choice[2].split("或")
        if 2 <= len(values) <= 4 and all(_literal(v) for v in values):
            if len({normalized_value(v) for v in values}) != len(values):
                return None, "needs_clarification", "duplicate_alternative"
            return _node("one_of", FIELD_ALIASES[choice[1]], "any", values), "supported", None
        return None, "unsupported", "unsupported_alternatives"
    canonical = parse_query(text)
    if canonical.budget:
        b = canonical.budget
        return _node("budget", "price", "le" if b.inclusive else "lt", [str(b.maximum)], unit="CNY"), "supported", None
    if len(canonical.specs) == 1:
        s = canonical.specs[0]
        if not _literal(s.value):
            return None, "unsupported", "exact_value_must_be_atomic"
        # Do not treat numeric syntax as an uninterpreted exact literal here.
        # The historical parser retains its separate colon-literal contract.
        if s.key == "capacity" and not _MEASURE.fullmatch(s.value):
            return None, "unsupported", "capacity_requires_explicit_scalar_unit"
        return _node("exact", s.key, "eq", [s.value]), "supported", None
    diagnostic = analyze_query(text)
    predicates = diagnostic.predicates
    if len(predicates) == 1 and predicates[0].strength == "soft":
        p = predicates[0]
        # Preserve only unambiguous soft exact values; never promote a budget.
        if p.kind == "exact" and _literal(p.value):
            return _node("exact", p.key, "eq", [p.value], strength="soft"), "supported", None
    if predicates or any(c.status == "ambiguous" for c in diagnostic.clauses):
        return None, "needs_clarification", "uncertain_or_unsupported_obligation"
    return None, "unsupported", "outside_bounded_semantic_grammar"


def propose_constraints(query: str) -> dict:
    """Produce a deterministic, query-only proposal. This is not permission."""
    if type(query) is not str:
        raise TypeError("query must be a plain original query string")
    proposal = {"schema": VERSION, "query_sha256": _digest(query), "operator": "all",
                "clauses": [], "layout": [], "issues": []}
    resource = query_resource_issue(query)
    if resource:
        proposal["clauses"] = [{"span": _span(0, len(query), query), "status": "unsupported",
                                "node": None, "reason": resource}]
        proposal["issues"] = [resource]
        return proposal
    cursor = 0
    for match in re.finditer(r"[^；;，,\n]+", query):
        text = match[0].strip()
        if not text:
            continue
        start = match.start() + len(match[0]) - len(match[0].lstrip())
        end = start + len(text)
        if cursor < start:
            proposal["layout"].append(_span(cursor, start, query))
        node, status, reason = _parse_clause(text)
        proposal["clauses"].append({"span": _span(start, end, query), "status": status,
                                     "node": node, "reason": reason})
        cursor = end
    if cursor < len(query):
        proposal["layout"].append(_span(cursor, len(query), query))
    hard = [c["node"] for c in proposal["clauses"] if c["node"] and c["node"]["strength"] == "hard"]
    budgets = [n for n in hard if n["kind"] == "budget"]
    issues = proposal["issues"]
    if len(budgets) != 1:
        issues.append("hard_budget_missing" if not budgets else "multiple_hard_budgets")
    if not any(n["kind"] in {"exact", "one_of"} and n["key"] in {"category", "title", "model"} for n in hard):
        issues.append("hard_product_scope_missing")
    # A deliberately conservative conflict rule, not a satisfiability solver.
    # Combining same-field constraints requires a future reviewed intersection.
    keys = [n["key"] for n in hard]
    if len(set(keys)) != len(keys):
        issues.append("duplicate_hard_field_needs_clarification")
    if any(c["status"] == "unsupported" for c in proposal["clauses"]):
        issues.append("unsupported_clause")
    if any(c["status"] == "needs_clarification" for c in proposal["clauses"]):
        issues.append("needs_clarification")
    return proposal


def validate_structure(query: str, proposal: object) -> tuple[str, ...]:
    """Validate a bounded JSON shape and source accounting; not its semantics."""
    if type(query) is not str:
        raise TypeError("query must be a plain original query string")
    def keys(obj, expected):
        return type(obj) is dict and set(obj) == set(expected.split())
    if not keys(proposal, "schema query_sha256 operator clauses layout issues"):
        return ("invalid_proposal_keys",)
    if any(type(proposal[k]) is not str for k in ("schema", "query_sha256", "operator")) or proposal["schema"] != VERSION or proposal["query_sha256"] != _digest(query) or proposal["operator"] != "all":
        return ("invalid_proposal_header",)
    if any(type(proposal[k]) is not list or len(proposal[k]) > 4096 for k in ("clauses", "layout", "issues")):
        return ("invalid_proposal_lists",)
    if any(type(issue) is not str for issue in proposal["issues"]):
        return ("invalid_issues",)
    spans = list(proposal["layout"])
    for clause in proposal["clauses"]:
        if not keys(clause, "span status node reason") or type(clause["status"]) is not str or clause["status"] not in {"supported", "unsupported", "needs_clarification"}:
            return ("invalid_clause",)
        if clause["reason"] is not None and type(clause["reason"]) is not str:
            return ("invalid_clause_reason",)
        spans.append(clause["span"])
        n = clause["node"]
        if n is None:
            continue
        if not keys(n, "kind key operator values unit strength"):
            return ("invalid_predicate_keys",)
        if any(type(n[k]) is not str for k in ("kind", "key", "operator", "strength")):
            return ("invalid_predicate_types",)
        if n["kind"] not in {"exact", "negative", "one_of", "quantity", "interval", "budget"} or n["key"] not in set(FIELD_ALIASES.values()) | {"price"}:
            return ("unknown_predicate",)
        if n["operator"] not in {"eq", "ne", "any", "ge", "gt", "le", "lt", "closed"} or n["strength"] not in {"hard", "soft"}:
            return ("unknown_operator_or_strength",)
        if (n["unit"] is not None and type(n["unit"]) is not str) or n["unit"] not in {None, "CNY", "mL"} or type(n["values"]) is not list or not 1 <= len(n["values"]) <= 4 or any(type(v) is not str or len(v) > 256 for v in n["values"]):
            return ("invalid_predicate_values",)
        contracts = {
            "exact": (n["operator"] == "eq" and n["unit"] is None and len(n["values"]) == 1),
            "negative": (n["operator"] == "ne" and n["key"] in {"color", "size", "package"} and n["unit"] is None and len(n["values"]) == 1),
            "one_of": (n["operator"] == "any" and n["unit"] is None and len(n["values"]) >= 2),
            "budget": (n["key"] == "price" and n["operator"] in {"le", "lt"} and n["unit"] == "CNY" and n["strength"] == "hard"),
            "quantity": (n["key"] == "capacity" and n["operator"] in {"eq", "le", "lt", "ge", "gt"} and n["unit"] == "mL"),
            "interval": (n["key"] == "capacity" and n["operator"] == "closed" and n["unit"] == "mL"),
        }
        if not contracts[n["kind"]]:
            return ("invalid_predicate_contract",)
        numeric = n["kind"] in {"quantity", "interval", "budget"}
        if numeric:
            expected = {"quantity": 2, "interval": 4, "budget": 1}[n["kind"]]
            if len(n["values"]) != expected or any(not re.fullmatch(_NUMBER, n["values"][i]) for i in range(0, expected, 2)):
                return ("invalid_numeric_values",)
            if any(n["values"][i] not in {"mL", "ml", "毫升", "L", "升"} for i in range(1, expected, 2)):
                return ("invalid_quantity_unit",)
            if n["kind"] == "interval" and _ml(*n["values"][:2]) > _ml(*n["values"][2:]):
                return ("reversed_interval",)
    for span in spans:
        if not keys(span, "start end text") or type(span["start"]) is not int or type(span["end"]) is not int or type(span["text"]) is not str:
            return ("invalid_source_span",)
        if not 0 <= span["start"] < span["end"] <= len(query) or query[span["start"]:span["end"]] != span["text"]:
            return ("mismatched_source_span",)
    cursor = 0
    for span in sorted(spans, key=lambda s: s["start"]):
        if span["start"] != cursor:
            return ("source_gap_or_overlap",)
        cursor = span["end"]
    return () if cursor == len(query) else ("source_gap_or_overlap",)


@dataclass(frozen=True)
class AcceptedConstraints:
    query: str
    canonical_json: str
    issues: tuple[str, ...]

    @property
    def ready(self):
        return not self.issues


def _serialize(proposal):
    return json.dumps(proposal, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def accept_semantics(query: str, proposal: object) -> AcceptedConstraints:
    """Trust only exact deterministic re-derivation, never model confidence."""
    issues = validate_structure(query, proposal)
    canonical = propose_constraints(query)
    if not issues and _serialize(proposal) != _serialize(canonical):
        issues = ("semantic_reparse_mismatch",)
    return AcceptedConstraints(query, _serialize(canonical), issues + tuple(canonical["issues"]))


def _prove(node, snapshot):
    key = node["key"]
    if node["kind"] == "budget":
        if snapshot.price is None:
            return "unknown", "price_unknown", []
        limit = Decimal(node["values"][0])
        ok = snapshot.price <= limit if node["operator"] == "le" else snapshot.price < limit
        return ("satisfied" if ok else "violated"), "current_selected_price", []
    # Negative evidence is restricted to an explicitly selected single axis.
    # Missing a claim (or substring matching a title) cannot establish absence.
    if node["kind"] == "negative" and key not in snapshot.available_axes:
        return "unknown", "negative_requires_selected_axis", []
    evidence_key = key if key in {"title", "brand", "category", "attribute"} else ("option:" if key in snapshot.available_axes else "attribute:") + key
    facts = [f for f in snapshot.facts if f.key == evidence_key and f.asin == snapshot.asin
             and f.variant == snapshot.variant and f.revision == snapshot.revision]
    if not facts:
        return "unknown", "current_fact_missing", []
    if node["kind"] == "negative" and any(not _literal(f.value) for f in facts):
        return "unknown", "negative_requires_atomic_selected_value", []
    values = {normalized_value(f.value) for f in facts}
    if key != "attribute" and len(values) != 1:
        return "unknown", "conflicting_current_facts", []
    if node["kind"] in {"quantity", "interval"}:
        measures = [_MEASURE.fullmatch(f.value.strip()) for f in facts]
        if any(m is None for m in measures):
            return "unknown", "scalar_quantity_with_supported_unit_required", []
        numbers = {_ml(m[1], m[2]) for m in measures}
        if len(numbers) != 1:
            return "unknown", "conflicting_current_quantities", []
        value = next(iter(numbers))
        v = node["values"]
        if node["kind"] == "interval":
            ok = _ml(v[0], v[1]) <= value <= _ml(v[2], v[3])
        else:
            target = _ml(v[0], v[1])
            ok = {"eq": value == target, "le": value <= target, "lt": value < target,
                  "ge": value >= target, "gt": value > target}[node["operator"]]
    else:
        expected = {normalized_value(v) for v in node["values"]}
        ok = values.isdisjoint(expected) if node["kind"] == "negative" else bool(values & expected)
    return ("satisfied" if ok else "violated"), "current_public_fact", [f.to_dict() for f in facts]


def verify_constraints(accepted: AcceptedConstraints, ledger: EvidenceLedger, *,
                       intended_asin: str, intended_options: Mapping) -> dict:
    """Review only; a snapshot/decision is not a transactional execution token."""
    if type(accepted) is not AcceptedConstraints or type(ledger) is not EvidenceLedger:
        raise TypeError("accepted constraints and an EvidenceLedger are required")
    canonical = propose_constraints(accepted.query)
    reasons = list(accept_semantics(accepted.query, canonical).issues) + list(accepted.issues)
    if accepted.canonical_json != _serialize(canonical):
        reasons.append("accepted_constraints_tampered")
    snapshot = ledger.current
    results = []
    if snapshot is None:
        reasons.append("no_public_observation")
    else:
        reasons.extend(snapshot_preconditions(snapshot, intended_asin, intended_options))
        for clause in canonical["clauses"]:
            node = clause["node"]
            if node is None:
                continue
            status, reason, facts = _prove(node, snapshot)
            results.append({"span": clause["span"], "node": node, "status": status,
                            "reason": reason, "evidence": facts})
            if node["strength"] == "hard" and status != "satisfied":
                reasons.append(status + ":" + node["key"] + ":" + reason)
    return {"schema": VERSION, "allowed": not reasons, "reasons": list(dict.fromkeys(reasons)),
            "query_sha256": _digest(accepted.query), "revision": snapshot.revision if snapshot else 0,
            "asin": snapshot.asin if snapshot else None, "variant": dict(snapshot.variant) if snapshot else {},
            "price": str(snapshot.price) if snapshot and snapshot.price is not None else None,
            "predicates": results, "execution_performed": False}
