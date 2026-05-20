import unittest
from datetime import date
from decimal import Decimal

from debtops.debtops.doctype.debt.schedule import (
    PaymentEvent,
    build_repayment_schedule,
    calculate_monthly_payment,
)


class TestDebtSchedule(unittest.TestCase):
    def test_monthly_payment_for_standard_loan(self):
        payment = calculate_monthly_payment(10000, 12, 12)
        self.assertEqual(payment, Decimal("888.49"))

    def test_overpayment_shortens_remaining_schedule(self):
        rows, summary = build_repayment_schedule(
            principal=10000,
            annual_rate_percent=12,
            duration_months=12,
            first_payment_date=date(2026, 6, 1),
            existing_events=[
                PaymentEvent(
                    schedule_id="SCH-0001",
                    row_type="Scheduled Payment",
                    due_date=date(2026, 6, 1),
                    payment_date=date(2026, 6, 1),
                    actual_paid_amount=Decimal("2000"),
                )
            ],
        )
        self.assertLess(summary["remaining_terms"], 11)
        self.assertEqual(rows[0]["remaining_balance"], Decimal("8100.00"))

    def test_underpayment_extends_remaining_schedule(self):
        _, original_summary = build_repayment_schedule(
            principal=10000,
            annual_rate_percent=12,
            duration_months=12,
            first_payment_date=date(2026, 6, 1),
        )
        _, underpaid_summary = build_repayment_schedule(
            principal=10000,
            annual_rate_percent=12,
            duration_months=12,
            first_payment_date=date(2026, 6, 1),
            existing_events=[
                PaymentEvent(
                    schedule_id="SCH-0001",
                    row_type="Scheduled Payment",
                    due_date=date(2026, 6, 1),
                    payment_date=date(2026, 6, 1),
                    actual_paid_amount=Decimal("100"),
                )
            ],
        )
        self.assertGreater(underpaid_summary["remaining_terms"], original_summary["remaining_terms"] - 1)

    def test_extra_payment_reduces_principal_only(self):
        rows, _ = build_repayment_schedule(
            principal=5000,
            annual_rate_percent=6,
            duration_months=24,
            first_payment_date=date(2026, 6, 1),
            existing_events=[
                PaymentEvent(
                    schedule_id="EXT-1",
                    row_type="Extra Payment",
                    due_date=date(2026, 6, 15),
                    payment_date=date(2026, 6, 15),
                    actual_paid_amount=Decimal("500"),
                )
            ],
        )
        self.assertEqual(rows[0]["actual_interest_amount"], Decimal("0"))
        self.assertEqual(rows[0]["remaining_balance"], Decimal("4500.00"))


if __name__ == "__main__":
    unittest.main()

