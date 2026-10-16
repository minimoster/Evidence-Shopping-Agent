"""Provider-independent, serial-only accounting for bounded transport attempts.

This module makes no requests, selects no provider, and does not enable real
evaluation. It is an accounting contract, not a sandbox or a billing guarantee.
A future transport must call ``reserve_attempt`` BEFORE EACH physical request,
including every retry, and must disable any unaccounted internal SDK retries.
The caller must obtain a conservative bound covering all possible billable work
for that request. Unknown pricing is not a zero-cost bound and fails closed.

After dispatch, settle only with a verified complete billed cost. Timeouts,
missing usage, ambiguous responses, and partial usage must be settled with
``None`` (or left reserved), retaining the entire bound. A later verified cost
may reconcile an uncertain attempt. A zero cost is appropriate only when the
complete attempt is known to be free. Reservations cannot be cancelled or used
to restore an attempt slot. A retry always needs a new reservation.

Use one ledger for the entire approved spend scope; recreating ledgers resets
their limits. All access must be serial or protected by an external lock. State
is in memory, not durable across crashes. This interface alone cannot constrain
an arbitrary caller, an existing transport, or a provider charging above its
declared bound. Such a breach is recorded and freezes all future reservations.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, MAX_EMAX, MIN_EMIN, localcontext
from typing import Literal


class SpendLimitError(RuntimeError):
    """A transport attempt must not be dispatched."""


class UnknownPricing(SpendLimitError):
    """No conservative USD bound was supplied."""


class SpendCapExceeded(SpendLimitError):
    """The next bound exceeds the remaining approved spend."""


class AttemptLimitExceeded(SpendLimitError):
    """The physical-attempt limit, including retries, is exhausted."""


class LedgerFrozen(SpendLimitError):
    """A prior billed cost breached its reservation."""


class AlreadySettled(ValueError):
    """A completed settlement cannot be overwritten or counted twice."""


@dataclass(frozen=True)
class AttemptReservation:
    """An immutable view; attempt IDs are local to their originating ledger."""

    attempt_id: int
    reserved_usd: Decimal
    retry_of: int | None = None
    status: Literal["reserved", "uncertain", "settled", "breached"] = "reserved"
    billed_usd: Decimal | None = None


class ReservationBreach(SpendLimitError):
    """The billed cost was recorded, but exceeded the reserved upper bound."""

    def __init__(self, attempt: AttemptReservation):
        self.attempt = attempt
        super().__init__("billed cost exceeded its reservation; ledger frozen")


@dataclass(frozen=True)
class SpendSnapshot:
    total_cap_usd: Decimal
    max_attempts: int
    attempts_used: int
    known_billed_usd: Decimal
    reserved_unknown_usd: Decimal
    accounted_exposure_usd: Decimal
    remaining_cap_usd: Decimal
    actual_cost_usd: Decimal | None
    unsettled_attempts: int
    uncertain_attempts: int
    frozen: bool
    breach_attempt_ids: tuple[int, ...]

    def to_dict(self) -> dict:
        """JSON-safe exact USD strings, never float or fabricated unknown zero.

        ``remaining_cap_usd`` is arithmetic headroom, not dispatch permission;
        a frozen ledger or exhausted attempt limit still forbids dispatch.
        ``known_billed_usd`` is a subtotal, not total actual spend while any
        attempt is unsettled, even if its reserved bound happens to be zero.
        """
        return {
            "schema_version": "spend-ledger-v1",
            "total_cap_usd": str(self.total_cap_usd),
            "max_attempts": self.max_attempts,
            "attempts_used": self.attempts_used,
            "known_billed_usd": str(self.known_billed_usd),
            "reserved_unknown_usd": str(self.reserved_unknown_usd),
            "accounted_exposure_usd": str(self.accounted_exposure_usd),
            "remaining_cap_usd": str(self.remaining_cap_usd),
            "actual_cost_usd": (None if self.actual_cost_usd is None
                                else str(self.actual_cost_usd)),
            "unsettled_attempts": self.unsettled_attempts,
            "uncertain_attempts": self.uncertain_attempts,
            "frozen": self.frozen,
            "breach_attempt_ids": list(self.breach_attempt_ids),
        }


def _usd(value: Decimal, name: str) -> Decimal:
    # Refuse floats, strings and bools instead of silently rounding/coercing.
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be an explicit Decimal USD amount")
    if not value.is_finite() or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return value


def _exact_sum(values) -> Decimal:
    """Add Decimal values without rounding under the caller's decimal context."""
    values = tuple(values)
    if not values:
        return Decimal(0)
    lowest_exponent = min(value.as_tuple().exponent for value in values)
    highest_place = max(value.adjusted() for value in values)
    # Extra digits allow carry from every summand. The subtraction below uses
    # copy_negate(), not context-sensitive unary minus.
    precision = max(1, highest_place - lowest_exponent + 1) + len(str(len(values))) + 1
    with localcontext() as context:
        context.prec = precision
        context.Emax = MAX_EMAX
        context.Emin = MIN_EMIN
        return sum(values, Decimal(0))


class SpendLedger:
    """In-memory accounting only; callers must serialize all ledger access."""

    def __init__(self, *, total_cap_usd: Decimal, max_attempts: int):
        self._total_cap_usd = _usd(total_cap_usd, "total_cap_usd")
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        self._max_attempts = max_attempts
        self._attempts: dict[int, AttemptReservation] = {}
        self._frozen = False

    @property
    def attempts(self) -> tuple[AttemptReservation, ...]:
        return tuple(self._attempts.values())

    def snapshot(self) -> SpendSnapshot:
        attempts = self.attempts
        unsettled = tuple(item for item in attempts if item.billed_usd is None)
        known = _exact_sum(item.billed_usd for item in attempts
                           if item.billed_usd is not None)
        reserved = _exact_sum(item.reserved_usd for item in unsettled)
        exposure = _exact_sum((known, reserved))
        remaining = max(Decimal(0), _exact_sum((self._total_cap_usd, exposure.copy_negate())))
        return SpendSnapshot(
            total_cap_usd=self._total_cap_usd,
            max_attempts=self._max_attempts,
            attempts_used=len(attempts),
            known_billed_usd=known,
            reserved_unknown_usd=reserved,
            accounted_exposure_usd=exposure,
            remaining_cap_usd=remaining,
            actual_cost_usd=None if unsettled else known,
            unsettled_attempts=len(unsettled),
            uncertain_attempts=sum(item.status == "uncertain" for item in attempts),
            frozen=self._frozen,
            breach_attempt_ids=tuple(item.attempt_id for item in attempts
                                     if item.status == "breached"),
        )

    def _get_attempt(self, attempt_id: int) -> AttemptReservation:
        if type(attempt_id) is not int:
            raise TypeError("attempt_id must be an integer from this ledger")
        if attempt_id not in self._attempts:
            raise KeyError("unknown attempt_id for this ledger")
        return self._attempts[attempt_id]

    def reserve_attempt(self, max_cost_usd: Decimal | None, *,
                        retry_of: int | None = None) -> AttemptReservation:
        """Reserve BEFORE one dispatch; retries cannot reuse a reservation.

        ``None`` means unknown pricing and is rejected. An explicit Decimal
        zero means the caller has verified a zero upper bound, not missing
        usage. Rejected reservations mutate neither exposure nor attempt count.
        ``retry_of`` links an existing attempt for audit, without special budget.
        """
        if self._frozen:
            raise LedgerFrozen("prior reservation breach forbids further dispatch")
        if max_cost_usd is None:
            raise UnknownPricing("a conservative per-attempt USD bound is required")
        bound = _usd(max_cost_usd, "max_cost_usd")
        if retry_of is not None:
            self._get_attempt(retry_of)
        snapshot = self.snapshot()
        if snapshot.attempts_used >= self._max_attempts:
            raise AttemptLimitExceeded("transport-attempt budget exhausted, including retries")
        if _exact_sum((snapshot.accounted_exposure_usd, bound)) > self._total_cap_usd:
            raise SpendCapExceeded("reservation would exceed the total USD cap")
        attempt = AttemptReservation(snapshot.attempts_used + 1, bound, retry_of)
        self._attempts[attempt.attempt_id] = attempt
        return attempt

    def settle_attempt(self, attempt_id: int,
                       billed_cost_usd: Decimal | None) -> AttemptReservation:
        """Record verified complete cost, or keep the full bound if unknown.

        Uncertain attempts may later be reconciled with a verified amount.
        Settled/breached costs cannot be overwritten, even by the same amount.
        A cost above its bound is recorded BEFORE ReservationBreach is raised;
        later reservations are forbidden, but outstanding costs can still be
        settled. Invalid amounts leave the prior reservation intact.
        """
        attempt = self._get_attempt(attempt_id)
        if attempt.status in {"settled", "breached"}:
            raise AlreadySettled("attempt already has a complete billed cost")
        if billed_cost_usd is None:
            if attempt.status == "uncertain":
                raise AlreadySettled("attempt already marked uncertain; provide a verified cost")
            updated = replace(attempt, status="uncertain")
        else:
            cost = _usd(billed_cost_usd, "billed_cost_usd")
            breached = cost > attempt.reserved_usd
            updated = replace(attempt, billed_usd=cost,
                              status="breached" if breached else "settled")
        self._attempts[attempt_id] = updated
        if updated.status == "breached":
            self._frozen = True
            raise ReservationBreach(updated)
        return updated
