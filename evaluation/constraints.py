"""Query-only compilation with an explicit, conservative grammar coverage audit.

This is an adapter around ``prototype.requirements.parse_query``, not a second
parser or general NLU system. The original query and its canonical requirements
are never rewritten: pass ``compile_query(query).requirements`` to the existing
purchase guard, which independently reparses the original query.

Audit statuses describe the narrow parser's clauses, not real-world semantic
coverage. Every input character belongs to one clause or one layout span.
Offsets are Python Unicode character offsets, not byte or UTF-16 offsets.
No observation, TaskFacts, hidden annotations, model, or catalog is an input.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from prototype.requirements import (
    AMBIGUOUS_VALUE,
    FIELD_ALIASES,
    QueryRequirements,
    SourceSpan,
    natural_field_match,
    natural_value_is_ambiguous,
    parse_query,
    query_resource_issue,
)


COMPILER_VERSION = "query-only-audit-v3-resource-bounded-not-general-NLU"
LIMITATIONS = (
    "Only explicit colon clauses and bounded natural labeled clauses are supported; this is not general NLU.",
    "Natural syntax still requires a field label and exact value, or an explicit CNY maximum; free prose is not inferred.",
    "Unsupported text is retained and blocks readiness; no task annotations or hidden facts are used.",
    "Ambiguous means a duplicate constraint or an existing lexical ambiguity marker, not semantic inference.",
    "Coverage measures literal clause/character accounting, not understanding of all shopping intent.",
    "Values remain exact lexical constraints; no synonyms, conversions, missing currency, or budgets are inferred.",
    "Readiness is not purchase authorization; the unchanged guard must verify current public evidence.",
    "Before regex matching: at most 4096 query characters, 256 per clause, and 8 consecutive whitespace characters.",
)

# Match the existing parser's clause boundaries for reporting only. Acceptance
# always comes from parse_query, never from this expression or the audit hints.
_CLAUSES = re.compile(r"[^；;，,\n]+")
_FRAGMENT_GLOBAL_ISSUES = frozenset({"budget_unknown", "product_scope_missing", "empty_query"})
ClauseStatus = Literal["supported", "unsupported", "ambiguous"]
ClauseKind = Literal["budget", "spec", "unparsed"]


@dataclass(frozen=True)
class ClauseAudit:
    span: SourceSpan
    status: ClauseStatus
    kind: ClauseKind
    key: str | None
    value_span: SourceSpan | None
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "span": self.span.to_dict(),
            "status": self.status,
            "kind": self.kind,
            "key": self.key,
            "value_span": self.value_span.to_dict() if self.value_span else None,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class CoverageAudit:
    total_clauses: int
    supported_clauses: int
    unsupported_clauses: int
    ambiguous_clauses: int
    query_characters: int
    supported_characters: int
    unsupported_characters: int
    ambiguous_characters: int
    layout_characters: int
    span_coverage_complete: bool

    @property
    def supported_clause_fraction(self) -> float:
        """A descriptive fraction, not readiness, semantic recall, or success."""
        return self.supported_clauses / self.total_clauses if self.total_clauses else 0.0

    def to_dict(self) -> dict:
        return {
            "total_clauses": self.total_clauses,
            "supported_clauses": self.supported_clauses,
            "unsupported_clauses": self.unsupported_clauses,
            "ambiguous_clauses": self.ambiguous_clauses,
            "query_characters": self.query_characters,
            "supported_characters": self.supported_characters,
            "unsupported_characters": self.unsupported_characters,
            "ambiguous_characters": self.ambiguous_characters,
            "layout_characters": self.layout_characters,
            "span_coverage_complete": self.span_coverage_complete,
            "supported_clause_fraction": self.supported_clause_fraction,
        }


@dataclass(frozen=True)
class CompilationAudit:
    clauses: tuple[ClauseAudit, ...]
    layout_spans: tuple[SourceSpan, ...]
    issues: tuple[str, ...]
    coverage: CoverageAudit

    def to_dict(self) -> dict:
        return {
            "clauses": [clause.to_dict() for clause in self.clauses],
            "layout_spans": [span.to_dict() for span in self.layout_spans],
            "issues": list(self.issues),
            "coverage": self.coverage.to_dict(),
            "span_unit": "python_unicode_character_offsets",
            "span_interval": "start_inclusive_end_exclusive",
        }


@dataclass(frozen=True)
class QueryCompilation:
    requirements: QueryRequirements
    audit: CompilationAudit

    @property
    def ready(self) -> bool:
        # Audit labels cannot turn a rejected query into an executable one.
        return self.requirements.ready

    def to_dict(self) -> dict:
        """Return a fresh JSON-safe representation for logs or a model prompt.

        Query/value strings remain untrusted data even when syntactically
        supported. This export is not an instruction to execute their contents.
        """
        return {
            "compiler": COMPILER_VERSION,
            "requirements": self.requirements.to_dict(),
            "audit": self.audit.to_dict(),
            "ready": self.ready,
            "limitations": list(LIMITATIONS),
        }


def _shift(span: SourceSpan, offset: int) -> SourceSpan:
    return SourceSpan(span.start + offset, span.end + offset, span.text)


def _ambiguous_unparsed(clause: str) -> bool:
    """Classify only an existing marker after a recognized label.

    Unknown prose/labels stay unsupported, rather than pretending to understand
    their intent. This diagnostic never supplies a requirement to the guard.
    """
    natural = natural_field_match(clause)
    if natural:
        return natural_value_is_ambiguous(natural.group("value"))
    if re.match(r"^(?:预算|价格|售价|总价)", clause):
        return bool(AMBIGUOUS_VALUE.search(clause) or re.search(r"(?:差不多|大致|上下|出头|偏好|最好)", clause))
    parts = re.split(r"[:：]", clause, maxsplit=1)
    if len(parts) != 2:
        return False
    label, value = parts[0].strip().casefold(), parts[1]
    return (label in FIELD_ALIASES or label in {"预算", "budget"}) and bool(AMBIGUOUS_VALUE.search(value))


def _audit_clause(span: SourceSpan, requirements: QueryRequirements) -> ClauseAudit:
    # A fragment parse is diagnostic only. In particular it recovers source
    # spans for individually valid budgets discarded by the canonical parser
    # when multiple budgets occur. Local missing-budget/scope issues must not
    # be attached to an otherwise supported individual clause.
    fragment = parse_query(span.text)
    if fragment.budget is not None:
        duplicate = "multiple_budgets" in requirements.issues
        return ClauseAudit(
            span, "ambiguous" if duplicate else "supported", "budget", "budget",
            _shift(fragment.budget.amount_span, span.start),
            ("multiple_budgets",) if duplicate else (),
        )
    if fragment.specs:
        spec = fragment.specs[0]
        issue = "duplicate_spec:" + spec.key
        duplicate = issue in requirements.issues
        return ClauseAudit(
            span, "ambiguous" if duplicate else "supported", "spec", spec.key,
            _shift(spec.value_span, span.start), (issue,) if duplicate else (),
        )
    reasons = tuple(issue for issue in fragment.issues if issue not in _FRAGMENT_GLOBAL_ISSUES)
    # Missing currency and a nonpositive amount are definite grammar failures,
    # not ambiguity just because a valid comparator contains an ambiguity token.
    definite_failure = any(issue in {"budget_currency_missing", "budget_not_positive"} for issue in reasons)
    ambiguous = not definite_failure and _ambiguous_unparsed(span.text)
    if ambiguous:
        reasons += ("ambiguous_value_marker",)
    return ClauseAudit(span, "ambiguous" if ambiguous else "unsupported", "unparsed", None, None, reasons)


def compile_query(query: str) -> QueryCompilation:
    """Compile only a plain query string, without repairing or enriching it.

    The returned requirements equal parse_query(query), including all issues and
    unparsed spans. Task/goal objects, mappings, and extra arguments are rejected.
    Unsupported clauses never disappear from either the requirements or audit.
    """
    if type(query) is not str:
        raise TypeError("query must be a plain string, not a task/goal object or hidden annotations")
    requirements = parse_query(query)
    resource_issue = query_resource_issue(query)
    if resource_issue is not None:
        # Do not run fragment/ambiguity regexes on a resource-rejected input.
        span = SourceSpan(0, len(query), query)
        clause = ClauseAudit(span, "unsupported", "unparsed", None, None, (resource_issue,))
        coverage = CoverageAudit(1, 0, 1, 0, len(query), 0, len(query), 0, 0, True)
        return QueryCompilation(requirements, CompilationAudit((clause,), (),
                                requirements.issues, coverage))
    clauses: list[ClauseAudit] = []
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
        clauses.append(_audit_clause(SourceSpan(start, end, text), requirements))
        cursor = end
    if cursor < len(query):
        layout.append(SourceSpan(cursor, len(query), query[cursor:]))

    # Check actual interval continuity and source equality, not just aggregate
    # lengths, so an omitted/overlapping span cannot masquerade as full coverage.
    spans = sorted([clause.span for clause in clauses] + layout, key=lambda span: span.start)
    cursor = 0
    complete = True
    for span in spans:
        if span.start != cursor or span.end <= span.start or query[span.start:span.end] != span.text:
            complete = False
        cursor = span.end
    complete = complete and cursor == len(query)

    def count(status: ClauseStatus) -> int:
        return sum(clause.status == status for clause in clauses)

    def characters(status: ClauseStatus) -> int:
        return sum(clause.span.end - clause.span.start for clause in clauses if clause.status == status)

    coverage = CoverageAudit(
        len(clauses), count("supported"), count("unsupported"), count("ambiguous"), len(query),
        characters("supported"), characters("unsupported"), characters("ambiguous"),
        sum(span.end - span.start for span in layout), complete,
    )
    audit = CompilationAudit(tuple(clauses), tuple(layout), requirements.issues, coverage)
    return QueryCompilation(requirements, audit)
