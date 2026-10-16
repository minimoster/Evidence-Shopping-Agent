"""Bounded, query-only predicate diagnostics; never a purchase compiler.

This adds a *separate* analysis vocabulary for labeled negative/soft constraints
and explicit natural budgets. It accepts only the original plain query string.
It does not consume observations, task IDs, annotations, catalogs, or gold, call a
model, infer synonyms, or supply richer predicates to the existing guard.

``canonical`` is exactly ``compile_query(query)``. Its requirements retain all
original failures and are the only existing guard interface. A recognized audit
clause is not semantic completeness, executable coverage, or purchase permission.
New predicates lack evidence verifiers: in particular absence of a positive fact
must never be interpreted as proof of a negative predicate. Offsets are Python
Unicode character offsets, with inclusive starts and exclusive ends.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
import hashlib
import re
from typing import Literal

from evaluation.constraints import QueryCompilation, compile_query
from prototype.requirements import (
    FIELD_ALIASES, SourceSpan, natural_value_is_ambiguous, normalized_value, parse_query,
    query_resource_issue,
)


ANALYZER_VERSION = "query-only-predicate-audit-v2-resource-bounded-not-purchase-authority"
LIMITATIONS = (
    "Finite labeled Chinese clause grammar, plus canonical colon literals; not general NLU.",
    "No inferred product scope, implicit currency, synonyms, unit conversion, ranges or alternatives.",
    "Approximate and nominal budgets are not hard ceilings; soft predicates do not relax hard ones.",
    "Recognized means grammar recognition, not semantic completeness or public-evidence proof.",
    "All new predicates are audit-only and are not accepted by the unchanged purchase guard.",
    "Complete source accounting does not establish correct interpretation of shopping intent.",
    "Quoted field values remain untrusted data, never executable instructions.",
    "Resource bounds reject oversized queries, clauses or whitespace runs without dropping source text.",
)
Strength = Literal["hard", "soft", "uncertain"]
PredicateKind = Literal["exact", "negative", "budget_ceiling", "budget_target"]
ClauseStatus = Literal["recognized", "unsupported", "ambiguous"]
Operator = Literal["eq", "ne", "le", "lt", "target"]


@dataclass(frozen=True)
class TypedPredicate:
    kind: PredicateKind
    key: str
    operator: Operator
    value: str
    strength: Strength
    source_span: SourceSpan
    value_span: SourceSpan
    marker_spans: tuple[SourceSpan, ...] = ()
    currency: str | None = None
    currency_spans: tuple[SourceSpan, ...] = ()
    approximate: bool = False

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "key": self.key, "operator": self.operator,
            "value": self.value, "strength": self.strength,
            "source_span": self.source_span.to_dict(), "value_span": self.value_span.to_dict(),
            "marker_spans": [span.to_dict() for span in self.marker_spans],
            "currency": self.currency, "currency_spans": [span.to_dict() for span in self.currency_spans],
            "approximate": self.approximate, "audit_only": True,
        }


@dataclass(frozen=True)
class AnalyzedClause:
    span: SourceSpan
    status: ClauseStatus
    predicates: tuple[TypedPredicate, ...]
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"span": self.span.to_dict(), "status": self.status,
                "predicates": [predicate.to_dict() for predicate in self.predicates],
                "reasons": list(self.reasons)}


@dataclass(frozen=True)
class QueryAnalysis:
    query: str
    canonical: QueryCompilation
    clauses: tuple[AnalyzedClause, ...]
    layout_spans: tuple[SourceSpan, ...]
    issues: tuple[str, ...]
    span_coverage_complete: bool

    @property
    def predicates(self) -> tuple[TypedPredicate, ...]:
        return tuple(predicate for clause in self.clauses for predicate in clause.predicates)

    @property
    def purchase_authorized(self) -> bool:
        """Always false, including when the unchanged canonical grammar is ready."""
        return False

    def to_dict(self) -> dict:
        counts = {status: sum(clause.status == status for clause in self.clauses)
                  for status in ("recognized", "unsupported", "ambiguous")}
        return {
            "analyzer": ANALYZER_VERSION, "query": self.query,
            "query_sha256": hashlib.sha256(self.query.encode("utf-8")).hexdigest(),
            "clauses": [clause.to_dict() for clause in self.clauses],
            "layout_spans": [span.to_dict() for span in self.layout_spans],
            "issues": list(self.issues), "canonical": self.canonical.to_dict(),
            "coverage": {"total_clauses": len(self.clauses), "clause_counts": counts,
                         "query_characters": len(self.query),
                         "span_coverage_complete": self.span_coverage_complete,
                         "span_unit": "python_unicode_character_offsets",
                         "span_interval": "start_inclusive_end_exclusive"},
            "audit_only": True, "semantic_completeness_verified": False,
            "purchase_authorized": False, "limitations": list(LIMITATIONS),
        }


_LABELS = "|".join(re.escape(label) for label in sorted(FIELD_ALIASES, key=len, reverse=True))
_LABEL = r"(?P<label>" + _LABELS + r")"
_SOFT = r"最好|优先|尽量|希望"
_NEGATIVE = r"不得为|不能是|不能为|不是|不要|不选|排除"
_FIELD = re.compile(
    r"(?:(?P<lead_soft>" + _SOFT + r")\s*)?" + _LABEL + r"\s*[:：]?\s*"
    r"(?:(?P<inner_soft>" + _SOFT + r")\s*)?"
    r"(?P<op>" + _NEGATIVE + r"|必须是|必须为|要求为|需要为|是|为|要)?\s*"
    r"(?P<value>.+?)\s*(?P<tail_soft>" + _SOFT + r")?\s*。?", re.IGNORECASE,
)
_BUDGET_LABEL = r"(?P<label>预算|价格|售价|budget)"
_BUDGET_START = (
    r"(?:(?P<lead_soft>" + _SOFT + r")\s*)?" + _BUDGET_LABEL
    + r"\s*[:：]?\s*(?:(?P<inner_soft>" + _SOFT + r")\s*)?(?:为|是)?\s*"
    + r"(?:(?P<approx_before>大约|大概|差不多|约)\s*)?"
)
_AMOUNT = (r"(?P<prefix>人民币|CNY|[¥￥])?\s*(?P<amount>[0-9]+(?:\.[0-9]{1,2})?)"
           r"\s*(?P<suffix>元)?")
_END = r"\s*(?P<approx_after>左右|上下)?\s*。?"
_BEFORE = re.compile(
    _BUDGET_START + r"(?P<op>不能超过|不要超过|不得超过|不得高于|不超过|不高于|最多|至多|最高|上限(?:为)?|<=|≤|低于|少于|<)\s*"
    + r"(?:(?P<approx_amount>大约|大概|约)\s*)?" + _AMOUNT + _END, re.IGNORECASE,
)
_AFTER = re.compile(
    _BUDGET_START + r"(?:控制在|在)?\s*" + _AMOUNT
    + r"\s*(?P<op>以内|以下|内)" + _END, re.IGNORECASE,
)
_TARGET = re.compile(_BUDGET_START + _AMOUNT + _END, re.IGNORECASE)
_CLAUSES = re.compile(r"[^；;，,\n]+")
_AMBIGUOUS = re.compile(r"或|/|\||如果|除外|除了|左右|上下|大约|大概|最好|优先|尽量|不|约|至少|[~～<>≤≥]|\d\s*[-–—到至]\s*\d")
_KNOWN_START = re.compile(r"^(?:(?:" + _SOFT + r")\s*)?(?:" + _LABELS + r"|预算|价格|售价|budget)", re.IGNORECASE)


def _group_span(match: re.Match, group: str, source: SourceSpan) -> SourceSpan | None:
    if group not in match.re.groupindex or match.start(group) < 0:
        return None
    raw = match.group(group)
    trimmed = raw.strip()
    if not trimmed:
        return None
    start = source.start + match.start(group) + len(raw) - len(raw.lstrip())
    return SourceSpan(start, start + len(trimmed), trimmed)


def _groups(match: re.Match, names: tuple[str, ...], source: SourceSpan) -> tuple[SourceSpan, ...]:
    return tuple(span for name in names if (span := _group_span(match, name, source)) is not None)


def _budget(source: SourceSpan) -> AnalyzedClause | None:
    match = _BEFORE.fullmatch(source.text) or _AFTER.fullmatch(source.text) or _TARGET.fullmatch(source.text)
    if match is None:
        return None
    if not (match.group("prefix") or match.group("suffix")):
        return AnalyzedClause(source, "unsupported", (), ("budget_currency_missing",))
    if Decimal(match.group("amount")) <= 0:
        return AnalyzedClause(source, "unsupported", (), ("budget_not_positive",))
    markers = _groups(match, ("lead_soft", "inner_soft", "op", "approx_before", "approx_amount", "approx_after"), source)
    approximate = any(name.startswith("approx") and name in match.re.groupindex and match.group(name)
                      for name in ("approx_before", "approx_amount", "approx_after"))
    soft = bool(match.group("lead_soft") or match.group("inner_soft"))
    op = match.groupdict().get("op")
    strength: Strength = "soft" if soft else "uncertain" if approximate or op is None else "hard"
    kind: PredicateKind = "budget_ceiling" if op is not None else "budget_target"
    operator: Operator = "target" if op is None else "lt" if op in {"低于", "少于", "<"} else "le"
    value_span = _group_span(match, "amount", source)
    assert value_span is not None
    predicate = TypedPredicate(kind, "price", operator, value_span.text, strength, source,
                               value_span, markers, "CNY", _groups(match, ("prefix", "suffix"), source),
                               bool(approximate))
    reasons = ("approximate_budget_not_hard_ceiling",) if approximate else ()
    if kind == "budget_target":
        reasons += ("budget_target_not_hard_ceiling",)
    status: ClauseStatus = "ambiguous" if strength == "uncertain" else "recognized"
    return AnalyzedClause(source, status, (predicate,), reasons)


def _clause(source: SourceSpan) -> AnalyzedClause:
    budget = _budget(source)
    if budget is not None:
        return budget
    match = _FIELD.fullmatch(source.text)
    if match:
        soft = bool(match.group("lead_soft") or match.group("inner_soft") or match.group("tail_soft"))
        op = match.group("op")
        # Bare field/value juxtaposition is not a labeled exact-value grammar.
        if soft or op in set(_NEGATIVE.split("|")):
            value_span = _group_span(match, "value", source)
            assert value_span is not None
            if len(value_span.text) <= 120 and not natural_value_is_ambiguous(value_span.text):
                negative = op in set(_NEGATIVE.split("|"))
                conflicting_modality = soft and op in {"必须是", "必须为", "要求为", "需要为"}
                predicate = TypedPredicate(
                    "negative" if negative else "exact", FIELD_ALIASES[match.group("label").casefold()],
                    "ne" if negative else "eq", value_span.text,
                    "uncertain" if conflicting_modality else "soft" if soft else "hard", source,
                    value_span, _groups(match, ("lead_soft", "inner_soft", "op", "tail_soft"), source),
                )
                return AnalyzedClause(source, "ambiguous" if conflicting_modality else "recognized", (predicate,),
                                      ("conflicting_obligation_markers",) if conflicting_modality else ())
            return AnalyzedClause(source, "ambiguous", (), ("compound_or_ambiguous_value",))
    # Exact lexical clauses retain precisely the existing parser's semantics,
    # including colon-literal punctuation. They do not gain semantic inference.
    fragment = parse_query(source.text)
    if len(fragment.specs) == 1:
        spec = fragment.specs[0]
        value_span = SourceSpan(source.start + spec.value_span.start,
                                source.start + spec.value_span.end, spec.value_span.text)
        return AnalyzedClause(source, "recognized", (TypedPredicate(
            "exact", spec.key, "eq", spec.value, "hard", source, value_span,
        ),))
    ambiguous = bool(_KNOWN_START.search(source.text) and _AMBIGUOUS.search(source.text))
    return AnalyzedClause(source, "ambiguous" if ambiguous else "unsupported", (),
                          ("outside_bounded_predicate_grammar",))


def _audit_collisions(clauses: list[AnalyzedClause]) -> tuple[list[AnalyzedClause], tuple[str, ...]]:
    """Flag duplicate hard equalities/ceilings and direct lexical contradictions.

    This deliberately does not solve predicates, compare approximate amounts,
    merge budgets, choose alternatives, or claim all contradictions are detected.
    """
    reasons: dict[int, list[str]] = {}
    exact: dict[str, list[tuple[int, TypedPredicate]]] = {}
    ceilings = []
    for index, clause in enumerate(clauses):
        for predicate in clause.predicates:
            if predicate.strength != "hard":
                continue
            if predicate.kind == "exact":
                exact.setdefault(predicate.key, []).append((index, predicate))
            elif predicate.kind == "budget_ceiling":
                ceilings.append(index)
    if len(ceilings) > 1:
        for index in ceilings:
            reasons.setdefault(index, []).append("multiple_hard_budget_ceilings")
    for key, items in exact.items():
        if len(items) > 1:
            for index, _ in items:
                reasons.setdefault(index, []).append("duplicate_hard_exact:" + key)
    for index, clause in enumerate(clauses):
        for predicate in clause.predicates:
            if predicate.kind != "negative" or predicate.strength != "hard":
                continue
            for other_index, other in exact.get(predicate.key, []):
                if normalized_value(predicate.value) == normalized_value(other.value):
                    issue = "hard_exact_negative_conflict:" + predicate.key
                    reasons.setdefault(index, []).append(issue)
                    reasons.setdefault(other_index, []).append(issue)
    issues = tuple(dict.fromkeys(reason for values in reasons.values() for reason in values))
    return [replace(clause, status="ambiguous", reasons=tuple(dict.fromkeys(clause.reasons + tuple(reasons[index]))))
            if index in reasons else clause for index, clause in enumerate(clauses)], issues


def analyze_query(query: str) -> QueryAnalysis:
    """Analyze only a plain string, preserving the original canonical guard parse.

    No mapping/task wrapper, extra context argument, observation, or hidden-input
    fallback is accepted. The result must not replace ``QueryRequirements`` or
    be used as a guard acceptance decision.
    """
    if type(query) is not str:
        raise TypeError("query must be a plain string, not a task, mapping or annotations")
    canonical = compile_query(query)
    resource_issue = query_resource_issue(query)
    if resource_issue is not None:
        span = SourceSpan(0, len(query), query)
        clause = AnalyzedClause(span, "unsupported", (), (resource_issue,))
        return QueryAnalysis(query, canonical, (clause,), (),
                             (resource_issue, "unsupported_clauses_retained"), True)
    clauses: list[AnalyzedClause] = []
    layout: list[SourceSpan] = []
    cursor = 0
    for match in _CLAUSES.finditer(query):
        raw = match.group()
        text = raw.strip()
        if not text:
            continue
        start = match.start() + len(raw) - len(raw.lstrip())
        end = start + len(text)
        if cursor < start:
            layout.append(SourceSpan(cursor, start, query[cursor:start]))
        clauses.append(_clause(SourceSpan(start, end, text)))
        cursor = end
    if cursor < len(query):
        layout.append(SourceSpan(cursor, len(query), query[cursor:]))
    clauses, issues = _audit_collisions(clauses)
    if not any(predicate.kind == "budget_ceiling" and predicate.strength == "hard"
               for clause in clauses for predicate in clause.predicates):
        issues += ("no_explicit_hard_budget_ceiling",)
    if any(clause.status == "unsupported" for clause in clauses):
        issues += ("unsupported_clauses_retained",)
    if any(clause.status == "ambiguous" for clause in clauses):
        issues += ("ambiguous_clauses_retained",)
    spans = sorted([clause.span for clause in clauses] + layout, key=lambda span: span.start)
    cursor = 0
    complete = True
    for span in spans:
        if span.start != cursor or span.end <= span.start or query[span.start:span.end] != span.text:
            complete = False
        cursor = span.end
    complete = complete and cursor == len(query)
    return QueryAnalysis(query, canonical, tuple(clauses), tuple(layout), issues, complete)


def main(argv: list[str] | None = None) -> int:
    """Print diagnostic JSON including supplied query/spans. Do not pass secrets."""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--query", help="Original public query; never a task or annotation object")
    source.add_argument("--stdin", action="store_true", help="Read the exact query from stdin, without stripping")
    args = parser.parse_args(argv)
    query = sys.stdin.read() if args.stdin else args.query
    json.dump(analyze_query(query).to_dict(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
