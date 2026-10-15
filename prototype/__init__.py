"""Offline, standard-library-only shopping safety prototype. Not an Agent or RL policy."""

from .requirements import Budget, QueryRequirements, SourceSpan, SpecRequirement, parse_query
from .purchase_guard import EvidenceLedger, PurchaseDecision, verify_purchase

__all__ = [
    "Budget", "QueryRequirements", "SourceSpan", "SpecRequirement", "parse_query",
    "EvidenceLedger", "PurchaseDecision", "verify_purchase",
]
