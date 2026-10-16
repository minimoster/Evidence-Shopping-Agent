"""Offline accounting contracts only; no provider, transport or paid requests."""
from dataclasses import FrozenInstanceError
from decimal import Decimal, Inexact, Rounded, localcontext
import json
import unittest

from evaluation.spend import (
    AlreadySettled, AttemptLimitExceeded, LedgerFrozen, ReservationBreach,
    SpendCapExceeded, SpendLedger, UnknownPricing,
)


D = Decimal


class SpendTests(unittest.TestCase):
    def ledger(self, cap="1", attempts=5):
        return SpendLedger(total_cap_usd=D(cap), max_attempts=attempts)

    def test_exact_cap_is_allowed_but_next_reservation_is_not(self):
        ledger = self.ledger("0.3")
        ledger.reserve_attempt(D("0.1"))
        ledger.reserve_attempt(D("0.2"))
        before = ledger.snapshot()
        self.assertEqual(before.accounted_exposure_usd, D("0.3"))
        with self.assertRaises(SpendCapExceeded):
            ledger.reserve_attempt(D("0.000000000000000000000000000001"))
        self.assertEqual(ledger.snapshot(), before)

    def test_accounting_is_exact_even_under_low_precision_context(self):
        first = D("0.123456789012345678901234567890123456789")
        second = D("0.000000000000000000000000000000000000001")
        cap = D("0.123456789012345678901234567890123456790")
        with localcontext() as context:
            context.prec = 2
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            ledger = SpendLedger(total_cap_usd=cap, max_attempts=3)
            one = ledger.reserve_attempt(first)
            two = ledger.reserve_attempt(second)
            self.assertEqual(ledger.snapshot().accounted_exposure_usd, cap)
            ledger.settle_attempt(one.attempt_id, first)
            ledger.settle_attempt(two.attempt_id, second)
            self.assertEqual(ledger.snapshot().actual_cost_usd, cap)
            self.assertEqual(ledger.snapshot().remaining_cap_usd, D(0))
            with self.assertRaises(SpendCapExceeded):
                ledger.reserve_attempt(second)

    def test_known_cost_releases_only_unused_reservation(self):
        ledger = self.ledger()
        one = ledger.reserve_attempt(D("0.8"))
        self.assertIsNone(ledger.snapshot().actual_cost_usd)
        ledger.settle_attempt(one.attempt_id, D("0.2"))
        snapshot = ledger.snapshot()
        self.assertEqual(snapshot.known_billed_usd, D("0.2"))
        self.assertEqual(snapshot.reserved_unknown_usd, D(0))
        self.assertEqual(snapshot.remaining_cap_usd, D("0.8"))
        self.assertEqual(snapshot.actual_cost_usd, D("0.2"))
        self.assertEqual(snapshot.attempts_used, 1)
        ledger.reserve_attempt(D("0.8"))

    def test_every_retry_needs_its_own_slot_and_bound(self):
        ledger = self.ledger("0.6", attempts=2)
        first = ledger.reserve_attempt(D("0.3"))
        ledger.settle_attempt(first.attempt_id, None)
        retry = ledger.reserve_attempt(D("0.3"), retry_of=first.attempt_id)
        self.assertNotEqual(first.attempt_id, retry.attempt_id)
        self.assertEqual(retry.retry_of, first.attempt_id)
        ledger.settle_attempt(retry.attempt_id, D(0))
        self.assertEqual(ledger.snapshot().attempts_used, 2)
        self.assertEqual(ledger.snapshot().accounted_exposure_usd, D("0.3"))
        with self.assertRaises(AttemptLimitExceeded):
            ledger.reserve_attempt(D(0), retry_of=retry.attempt_id)

    def test_uncertain_attempt_retains_full_reservation_and_unknown_total(self):
        ledger = self.ledger()
        first = ledger.reserve_attempt(D("0.7"))
        ledger.settle_attempt(first.attempt_id, None)
        snapshot = ledger.snapshot()
        self.assertEqual(snapshot.reserved_unknown_usd, D("0.7"))
        self.assertEqual(snapshot.uncertain_attempts, 1)
        self.assertIsNone(snapshot.actual_cost_usd)
        with self.assertRaises(SpendCapExceeded):
            ledger.reserve_attempt(D("0.4"), retry_of=first.attempt_id)
        ledger.settle_attempt(first.attempt_id, D("0.1"))
        self.assertEqual(ledger.snapshot().actual_cost_usd, D("0.1"))
        self.assertEqual(ledger.snapshot().uncertain_attempts, 0)

    def test_pending_dispatch_cannot_be_reported_as_known_zero(self):
        ledger = self.ledger()
        self.assertEqual(ledger.snapshot().actual_cost_usd, D(0))
        ledger.reserve_attempt(D(0))
        self.assertIsNone(ledger.snapshot().actual_cost_usd)
        self.assertEqual(ledger.snapshot().reserved_unknown_usd, D(0))
        self.assertEqual(ledger.snapshot().unsettled_attempts, 1)
        self.assertIsNone(ledger.snapshot().to_dict()["actual_cost_usd"])

    def test_unknown_pricing_fails_before_any_state_change(self):
        ledger = self.ledger()
        before = ledger.snapshot()
        with self.assertRaises(UnknownPricing):
            ledger.reserve_attempt(None)
        self.assertEqual(ledger.snapshot(), before)

    def test_invalid_amounts_fail_closed_without_releasing_exposure(self):
        bad_decimals = (D("NaN"), D("sNaN"), D("Infinity"), D("-Infinity"), D("-0.01"))
        bad_types = (0.1, 0, "0.1", True)
        for value in bad_decimals + bad_types:
            with self.subTest(value=str(value)):
                with self.assertRaises((ValueError, TypeError)):
                    SpendLedger(total_cap_usd=value, max_attempts=2)
                ledger = self.ledger()
                before = ledger.snapshot()
                with self.assertRaises((ValueError, TypeError)):
                    ledger.reserve_attempt(value)
                self.assertEqual(ledger.snapshot(), before)
                attempt = ledger.reserve_attempt(D("0.5"))
                before = ledger.snapshot()
                with self.assertRaises((ValueError, TypeError)):
                    ledger.settle_attempt(attempt.attempt_id, value)
                self.assertEqual(ledger.snapshot(), before)

    def test_invalid_attempt_limits_are_rejected(self):
        for value in (True, False, 0, -1, 2.0, "2", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SpendLedger(total_cap_usd=D(1), max_attempts=value)

    def test_zero_cap_requires_explicit_zero_bound(self):
        ledger = self.ledger("0", attempts=1)
        with self.assertRaises(SpendCapExceeded):
            ledger.reserve_attempt(D("0.0001"))
        attempt = ledger.reserve_attempt(D(0))
        ledger.settle_attempt(attempt.attempt_id, D(0))
        self.assertEqual(ledger.snapshot().actual_cost_usd, D(0))
        with self.assertRaises(AttemptLimitExceeded):
            ledger.reserve_attempt(D(0))

    def test_duplicate_settlement_never_double_counts_or_refunds(self):
        ledger = self.ledger()
        attempt = ledger.reserve_attempt(D("0.5"))
        ledger.settle_attempt(attempt.attempt_id, D("0.4"))
        before = ledger.snapshot()
        for value in (D("0.4"), D(0), None):
            with self.subTest(value=value), self.assertRaises(AlreadySettled):
                ledger.settle_attempt(attempt.attempt_id, value)
            self.assertEqual(ledger.snapshot(), before)

    def test_duplicate_uncertainty_requires_verified_cost_to_reconcile(self):
        ledger = self.ledger()
        attempt = ledger.reserve_attempt(D("0.5"))
        ledger.settle_attempt(attempt.attempt_id, None)
        before = ledger.snapshot()
        with self.assertRaises(AlreadySettled):
            ledger.settle_attempt(attempt.attempt_id, None)
        self.assertEqual(ledger.snapshot(), before)

    def test_breach_is_recorded_and_freezes_even_with_total_cap_headroom(self):
        ledger = self.ledger("10")
        first = ledger.reserve_attempt(D("0.2"))
        outstanding = ledger.reserve_attempt(D("0.3"))
        with self.assertRaises(ReservationBreach) as raised:
            ledger.settle_attempt(first.attempt_id, D("0.21"))
        self.assertEqual(raised.exception.attempt.status, "breached")
        self.assertEqual(raised.exception.attempt.billed_usd, D("0.21"))
        snapshot = ledger.snapshot()
        self.assertTrue(snapshot.frozen)
        self.assertEqual(snapshot.breach_attempt_ids, (first.attempt_id,))
        self.assertEqual(snapshot.accounted_exposure_usd, D("0.51"))
        self.assertIsNone(snapshot.actual_cost_usd)
        with self.assertRaises(LedgerFrozen):
            ledger.reserve_attempt(D(0))
        with self.assertRaises(AlreadySettled):
            ledger.settle_attempt(first.attempt_id, D(0))
        ledger.settle_attempt(outstanding.attempt_id, D("0.1"))
        self.assertEqual(ledger.snapshot().actual_cost_usd, D("0.31"))
        self.assertTrue(ledger.snapshot().frozen)

    def test_breach_above_total_cap_keeps_full_actual_cost(self):
        ledger = self.ledger("0.2")
        attempt = ledger.reserve_attempt(D("0.2"))
        with self.assertRaises(ReservationBreach):
            ledger.settle_attempt(attempt.attempt_id, D("0.7"))
        snapshot = ledger.snapshot()
        self.assertEqual(snapshot.known_billed_usd, D("0.7"))
        self.assertEqual(snapshot.actual_cost_usd, D("0.7"))
        self.assertEqual(snapshot.remaining_cap_usd, D(0))

    def test_invalid_attempt_identifiers_do_not_mutate_ledger(self):
        ledger = self.ledger()
        ledger.reserve_attempt(D("0.2"))
        before = ledger.snapshot()
        for attempt_id in (0, 99, -1, True, "1", 1.0):
            with self.subTest(attempt_id=attempt_id):
                with self.assertRaises((KeyError, TypeError)):
                    ledger.settle_attempt(attempt_id, D(0))
                with self.assertRaises((KeyError, TypeError)):
                    ledger.reserve_attempt(D(0), retry_of=attempt_id)
                self.assertEqual(ledger.snapshot(), before)

    def test_public_records_and_snapshots_are_immutable(self):
        ledger = self.ledger()
        attempt = ledger.reserve_attempt(D("0.2"))
        with self.assertRaises(FrozenInstanceError):
            attempt.reserved_usd = D(0)
        with self.assertRaises(FrozenInstanceError):
            ledger.snapshot().attempts_used = 0
        self.assertIsInstance(ledger.attempts, tuple)

    def test_snapshot_serializes_precisely_and_preserves_unknown(self):
        ledger = self.ledger()
        attempt = ledger.reserve_attempt(D("0.100000000000000000000000000001"))
        unknown = json.loads(json.dumps(ledger.snapshot().to_dict(), allow_nan=False))
        self.assertIsNone(unknown["actual_cost_usd"])
        self.assertEqual(unknown["reserved_unknown_usd"], "0.100000000000000000000000000001")
        ledger.settle_attempt(attempt.attempt_id, D("0.000000000000000000000000000001"))
        known = json.loads(json.dumps(ledger.snapshot().to_dict(), allow_nan=False))
        self.assertEqual(D(known["actual_cost_usd"]), D("1E-30"))


if __name__ == "__main__":
    unittest.main()
