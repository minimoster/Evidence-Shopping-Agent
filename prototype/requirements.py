"""Deliberately narrow query-only rules, not a general natural-language parser.

Accepted example:
    品类:耳机；预算:不超过100元；品牌:声学；颜色:黑色

Every nonempty clause must match the documented grammar. Unsupported free prose,
soft preferences, alternatives, missing currency and missing/duplicate budgets
are retained as issues, never silently dropped to produce a purchase approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re


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
                "ready": self.ready, "parser": "explicit-clause-rules-v1-not-general-NLU"}


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
        match = _BUDGET_BEFORE.fullmatch(clause) or _BUDGET_AFTER.fullmatch(clause)
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
        if field_match:
            label = field_match.group("label").strip().casefold()
            key = FIELD_ALIASES.get(label)
            value_raw = field_match.group("value")
            value = value_raw.strip()
            if key and value and len(value) <= 120 and not AMBIGUOUS_VALUE.search(value):
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
