"""Bounded query-only clause rules, not a general natural-language parser.

Accepted example:
    品类:耳机；预算:不超过100元；品牌:声学；颜色:黑色

Every nonempty clause must match the documented grammar. Unsupported free prose,
soft preferences, alternatives, missing currency and missing/duplicate budgets
are retained as issues, never silently dropped to produce a purchase approval.

Also accepts explicit natural labels, e.g. ``商品名称是耳机，颜色为黑色，
价格不超过100元。``. A label and an exact value are still mandatory; this does
not infer categories from noun phrases, interpret functions or resolve prose.
Only natural clauses may end in the sentence terminator ``。``. No clause is
rewritten before source offsets are recorded or independently reparsed.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re


# Resource limits apply before any ambiguous/backtracking clause expression.
# Rejection retains the complete original source; never normalize or truncate it
# into a different executable request. These are grammar limits, not user intent.
MAX_QUERY_CHARACTERS = 4096
MAX_CLAUSE_CHARACTERS = 256
MAX_WHITESPACE_RUN = 8


def query_resource_issue(query: str) -> str | None:
    """Linear preflight shared by canonical and diagnostic parsers."""
    if len(query) > MAX_QUERY_CHARACTERS:
        return "query_length_limit"
    clause_length = whitespace_run = 0
    for character in query:
        clause_length = 0 if character in "；;，,\n" else clause_length + 1
        whitespace_run = whitespace_run + 1 if character.isspace() else 0
        if clause_length > MAX_CLAUSE_CHARACTERS:
            return "clause_length_limit"
        if whitespace_run > MAX_WHITESPACE_RUN:
            return "whitespace_run_limit"
    return None


# This is a small explicit vocabulary, not a learned or general semantic mapping.
FIELD_ALIASES = {
    "品类": "category", "类别": "category", "类目": "category", "category": "category",
    "品牌": "brand", "brand": "brand",
    "标题": "title", "商品名称": "title", "title": "title",
    "型号": "model", "model": "model",
    "颜色": "color", "颜色分类": "color", "色彩": "color", "color": "color", "colour": "color",
    "尺码": "size", "尺寸": "size", "size": "size",
    "容量": "capacity", "capacity": "capacity",
    "规格": "spec", "spec": "spec",
    "套餐": "package", "package": "package",
    "材质": "material", "material": "material",
    "属性": "attribute", "attribute": "attribute",
}
AMBIGUOUS_VALUE = re.compile(
    r"(?:或者|或|/|\||左右|大约|大概|尽量|最好|优先|不限|任意|随便|至少|至多|最多|以上|以下|"
    r"不超过|不低于|不要|不是|不带|不含|不能|可选|[<>≤≥~～])", re.IGNORECASE
)
# No implicit maxima, approximate tolerances, ranges, k/万 scaling or conversions.
_BUDGET_PREFIX = r"(?:预算|budget)\s*[:：]?\s*"
_AMOUNT = r"(?P<prefix>人民币\s*|CNY\s*|[¥￥]\s*)?(?P<amount>\d+(?:\.\d{1,2})?)(?P<suffix>\s*元)?"
_BUDGET_BEFORE = re.compile(
    _BUDGET_PREFIX + r"(?P<op>不超过|不高于|最多|上限(?:为)?|<=|≤|低于|少于|<)\s*" + _AMOUNT,
    re.IGNORECASE,
)
_BUDGET_AFTER = re.compile(
    _BUDGET_PREFIX + _AMOUNT + r"\s*(?P<op>以内|以下|内)", re.IGNORECASE,
)
# Natural syntax remains an explicit maximum, not an approximate spending target.
# An entire clause must match: prefixes/suffixes carrying additional intent are
# not removed. Currency and amount rules are identical to the original grammar.
# Do not accept fee-inclusive/quantity-total labels: the current guard proves a
# single selected product price, not shipping, tax or a multi-item order total.
_NATURAL_BUDGET_PREFIX = r"(?:预算|价格|售价)\s*(?:为|是)?\s*"
_NATURAL_BUDGET_BEFORE = re.compile(
    _NATURAL_BUDGET_PREFIX
    + r"(?P<op>不超过|不高于|不能超过|不要超过|最多|上限(?:为)?|<=|≤|低于|少于|<)\s*"
    + _AMOUNT + r"\s*。?", re.IGNORECASE,
)
_NATURAL_BUDGET_AFTER = re.compile(
    _NATURAL_BUDGET_PREFIX + r"(?:在)?\s*" + _AMOUNT
    + r"\s*(?P<op>以内|以下|内)\s*。?", re.IGNORECASE,
)
_NATURAL_LABELS = "|".join(sorted(
    (label for label in FIELD_ALIASES if not label.isascii()), key=len, reverse=True,
))
_NATURAL_FIELD = re.compile(
    r"(?P<label>" + _NATURAL_LABELS + r")\s*"
    r"(?:必须是|必须为|要求为|需要为|是|为|要)\s*(?P<value>.+?)\s*。?",
)
# Unlike colon-labelled values, natural values are not a quoted/literal data
# field. Do not turn conjunctions, negations, conditions or preferences into one
# exact spec. Conservative false negatives are intentional. This finite lexical
# check is not a claim to detect all semantic ambiguity in arbitrary language.
_NATURAL_UNSAFE_VALUE = re.compile(
    r"(?:和|与|及|且|但|同时|并|而|也|再|还|要|应|需|能|支持|适合|适用|无|非|不|"
    r"除了|除外|约|偏|希望|建议|推荐|例如|比如|之类|等|如果|只|像|一样|类似|"
    r"比较|稍|一点|一些|更|略|至|到|\d\s*[-–—]\s*\d|[。！？?:：;；，,、\n]|"
    r"\b(?:and|or|not|without|prefer|unless|if)\b)", re.IGNORECASE,
)


def natural_value_is_ambiguous(value: str) -> bool:
    """Bounded natural-clause diagnostic; never a semantic completeness proof."""
    return bool(AMBIGUOUS_VALUE.search(value) or _NATURAL_UNSAFE_VALUE.search(value))


def natural_field_match(clause: str):
    """Expose exactly the canonical natural-label matcher for coverage audits."""
    return _NATURAL_FIELD.fullmatch(clause)


@dataclass(frozen=True)
class SourceSpan:
    start: int
    end: int
    text: str

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "text": self.text}


@dataclass(frozen=True)
class Budget:
    maximum: Decimal
    inclusive: bool
    currency: str
    span: SourceSpan
    amount_span: SourceSpan

    def to_dict(self) -> dict:
        return {
            "maximum": str(self.maximum), "inclusive": self.inclusive,
            "currency": self.currency, "span": self.span.to_dict(),
            "amount_span": self.amount_span.to_dict(),
        }


@dataclass(frozen=True)
class SpecRequirement:
    key: str
    value: str
    span: SourceSpan
    value_span: SourceSpan

    def to_dict(self) -> dict:
        return {"key": self.key, "value": self.value, "span": self.span.to_dict(),
                "value_span": self.value_span.to_dict()}


@dataclass(frozen=True)
class QueryRequirements:
    query: str
    budget: Budget | None
    specs: tuple[SpecRequirement, ...]
    issues: tuple[str, ...]
    unparsed: tuple[SourceSpan, ...]

    @property
    def ready(self) -> bool:
        return not self.issues and self.budget is not None

    def to_dict(self) -> dict:
        return {"query": self.query, "budget": self.budget.to_dict() if self.budget else None,
                "specs": [spec.to_dict() for spec in self.specs],
                "issues": list(self.issues), "unparsed": [s.to_dict() for s in self.unparsed],
                "ready": self.ready, "parser": "bounded-clause-rules-v3-resource-bounded-not-general-NLU"}


def canonical_field(raw: str) -> str:
    """Canonicalize only documented axis labels; unknown labels stay distinct."""
    text = raw.strip().casefold()
    return FIELD_ALIASES.get(text, "raw:" + text)


def normalized_value(raw: str) -> str:
    """Exact lexical equality after case/whitespace normalization, no inference."""
    return re.sub(r"\s+", " ", raw).strip().casefold()


def parse_query(query: str) -> QueryRequirements:
    """Read only the supplied query. No observation, annotation or gold is accepted."""
    if not isinstance(query, str):
        raise TypeError("query must be a string, not a task/goal object")
    resource_issue = query_resource_issue(query)
    if resource_issue is not None:
        return QueryRequirements(query, None, (), (resource_issue,),
                                 (SourceSpan(0, len(query), query),))
    specs: list[SpecRequirement] = []
    issues: list[str] = []
    unparsed: list[SourceSpan] = []
    budgets: list[Budget] = []
    seen_keys: set[str] = set()
    # Separators themselves are grammar; spans use Python Unicode character offsets.
    for chunk in re.finditer(r"[^；;，,\n]+", query):
        raw = chunk.group()
        clause = raw.strip()
        if not clause:
            continue
        offset = chunk.start() + len(raw) - len(raw.lstrip())
        span = SourceSpan(offset, offset + len(clause), clause)
        match = (_BUDGET_BEFORE.fullmatch(clause) or _BUDGET_AFTER.fullmatch(clause)
                 or _NATURAL_BUDGET_BEFORE.fullmatch(clause)
                 or _NATURAL_BUDGET_AFTER.fullmatch(clause))
        if match:
            if not (match.group("prefix") or match.group("suffix")):
                issues.append("budget_currency_missing")
                unparsed.append(span)
                continue
            maximum = Decimal(match.group("amount"))
            if maximum <= 0:
                issues.append("budget_not_positive")
                unparsed.append(span)
                continue
            amount_start = offset + match.start("amount")
            budgets.append(Budget(
                maximum, match.group("op") not in {"低于", "少于", "<"}, "CNY", span,
                SourceSpan(amount_start, offset + match.end("amount"), match.group("amount")),
            ))
            continue
        field_match = re.fullmatch(r"(?P<label>[^:：]+)\s*[:：]\s*(?P<value>.+)", clause)
        natural = field_match is None
        if natural:
            field_match = natural_field_match(clause)
        if field_match:
            label = field_match.group("label").strip().casefold()
            key = FIELD_ALIASES.get(label)
            value_raw = field_match.group("value")
            value = value_raw.strip()
            ambiguous = natural_value_is_ambiguous(value) if natural else bool(AMBIGUOUS_VALUE.search(value))
            if key and value and len(value) <= 120 and not ambiguous:
                if key in seen_keys:
                    issues.append("duplicate_spec:" + key)
                seen_keys.add(key)
                value_start = offset + field_match.start("value") + len(value_raw) - len(value_raw.lstrip())
                specs.append(SpecRequirement(key, value, span,
                    SourceSpan(value_start, value_start + len(value), value)))
                continue
        unparsed.append(span)
        issues.append("unsupported_or_ambiguous_clause")
    budget = budgets[0] if len(budgets) == 1 else None
    if not budgets:
        issues.append("budget_unknown")
    elif len(budgets) > 1:
        issues.append("multiple_budgets")
    if not any(spec.key in {"category", "title", "model"} for spec in specs):
        issues.append("product_scope_missing")
    if not query.strip():
        issues.append("empty_query")
    return QueryRequirements(query, budget, tuple(specs), tuple(dict.fromkeys(issues)), tuple(unparsed))
