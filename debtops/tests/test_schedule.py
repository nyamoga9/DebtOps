import json
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from debtops.debtops.doctype.debt.schedule import (
    PaymentEvent,
    build_repayment_schedule,
    calculate_monthly_payment,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def doctype_fields(path):
    doctype = json.loads(path.read_text(encoding="utf-8"))
    return {field["fieldname"]: field for field in doctype["fields"]}


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

    def test_missed_payment_carries_interest_forward(self):
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
                    actual_paid_amount=Decimal("0"),
                )
            ],
        )
        self.assertEqual(rows[0]["actual_paid_amount"], Decimal("0.00"))
        self.assertEqual(rows[0]["actual_interest_amount"], Decimal("0.00"))
        self.assertEqual(rows[0]["interest_carry_forward"], Decimal("100.00"))
        self.assertEqual(rows[0]["remaining_balance"], Decimal("10000.00"))
        self.assertEqual(summary["remaining_balance"], Decimal("10000.00"))
        self.assertGreater(summary["remaining_terms"], 11)

    def test_unpaid_future_schedule_keeps_actual_balance_open(self):
        rows, summary = build_repayment_schedule(
            principal=10000,
            annual_rate_percent=12,
            duration_months=12,
            first_payment_date=date(2026, 6, 1),
        )
        self.assertEqual(summary["remaining_balance"], Decimal("10000.00"))
        self.assertEqual(rows[0]["remaining_balance"], Decimal("10000.00"))
        self.assertEqual(rows[-1]["projected_remaining_balance"], Decimal("0.00"))

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


class TestCurrencyMetadata(unittest.TestCase):
    def test_debt_currency_fields_use_selected_currency(self):
        fields = doctype_fields(REPO_ROOT / "debtops/debtops/doctype/debt/debt.json")
        for fieldname in (
            "opening_principal",
            "payment_amount_override",
            "monthly_payment",
            "remaining_balance",
            "total_paid",
            "total_interest_paid",
            "total_interest_remaining",
            "interest_carry_forward",
        ):
            self.assertEqual(fields[fieldname]["options"], "currency")

    def test_debt_base_currency_fields_use_company_currency(self):
        fields = doctype_fields(REPO_ROOT / "debtops/debtops/doctype/debt/debt.json")
        self.assertEqual(fields["company_currency"]["options"], "Currency")
        for fieldname in (
            "base_opening_principal",
            "base_monthly_payment",
            "base_remaining_balance",
            "base_total_interest_remaining",
        ):
            self.assertEqual(fields[fieldname]["options"], "company_currency")

    def test_debt_dashboard_totals_use_base_currency_fields(self):
        cards = {
            "total_debt_outstanding": "base_remaining_balance",
            "monthly_debt_payments": "base_monthly_payment",
            "projected_interest_remaining": "base_total_interest_remaining",
        }
        for card, fieldname in cards.items():
            path = REPO_ROOT / f"debtops/debtops/number_card/{card}/{card}.json"
            number_card = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(number_card["aggregate_function_based_on"], fieldname)

        chart_path = REPO_ROOT / "debtops/debtops/dashboard_chart/debt_originations/debt_originations.json"
        chart = json.loads(chart_path.read_text(encoding="utf-8"))
        self.assertEqual(chart["value_based_on"], "base_opening_principal")

    def test_schedule_currency_fields_use_row_currency(self):
        fields = doctype_fields(
            REPO_ROOT / "debtops/debtops/doctype/debt_repayment_schedule/debt_repayment_schedule.json"
        )
        self.assertEqual(fields["currency"]["options"], "Currency")
        for fieldname in (
            "scheduled_principal",
            "scheduled_interest",
            "scheduled_payment",
            "actual_paid_amount",
            "actual_principal_amount",
            "actual_interest_amount",
            "interest_carry_forward",
            "remaining_balance",
            "projected_remaining_balance",
        ):
            self.assertEqual(fields[fieldname]["options"], "currency")


if __name__ == "__main__":
    unittest.main()
