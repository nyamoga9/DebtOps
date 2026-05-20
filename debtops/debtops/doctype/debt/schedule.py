from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import Iterable

getcontext().prec = 28


@dataclass(frozen=True)
class PaymentEvent:
    schedule_id: str
    row_type: str
    due_date: date | None
    payment_date: date | None
    actual_paid_amount: Decimal
    journal_entry: str | None = None
    payment_account: str | None = None
    notes: str | None = None
    sort_index: int = 0


def add_months(source_date: date, months: int) -> date:
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    day = min(source_date.day, monthrange(year, month)[1])
    return date(year, month, day)


def as_decimal(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def money(value, precision: int = 2) -> Decimal:
    quant = Decimal("1").scaleb(-precision)
    return as_decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def iso_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def calculate_monthly_payment(
    principal,
    annual_rate_percent,
    duration_months: int,
    precision: int = 2,
) -> Decimal:
    principal = money(principal, precision)
    duration_months = int(duration_months or 0)
    if principal <= 0 or duration_months <= 0:
        return Decimal("0")

    monthly_rate = as_decimal(annual_rate_percent) / Decimal("100") / Decimal("12")
    if monthly_rate == 0:
        return money(principal / Decimal(duration_months), precision)

    payment = principal * monthly_rate / (Decimal("1") - ((Decimal("1") + monthly_rate) ** -duration_months))
    return money(payment, precision)


def _event_date(event: PaymentEvent) -> date:
    return event.payment_date or event.due_date or date.max


def _scheduled_payment_split(balance: Decimal, interest_due: Decimal, target_payment: Decimal, precision: int):
    total_due = money(balance + interest_due, precision)
    scheduled_payment = min(target_payment, total_due)
    scheduled_interest = min(interest_due, scheduled_payment)
    scheduled_principal = money(max(Decimal("0"), scheduled_payment - scheduled_interest), precision)
    scheduled_principal = min(scheduled_principal, balance)
    return scheduled_principal, scheduled_interest, scheduled_payment


def build_repayment_schedule(
    principal,
    annual_rate_percent,
    duration_months: int,
    first_payment_date,
    existing_events: Iterable[PaymentEvent] | None = None,
    target_payment=None,
    precision: int = 2,
    max_months: int = 600,
) -> tuple[list[dict], dict]:
    opening_principal = money(principal, precision)
    if opening_principal <= 0:
        return [], {
            "monthly_payment": Decimal("0"),
            "remaining_balance": Decimal("0"),
            "remaining_terms": 0,
            "maturity_date": None,
            "total_paid": Decimal("0"),
            "total_interest_paid": Decimal("0"),
            "total_interest_remaining": Decimal("0"),
            "interest_carry_forward": Decimal("0"),
        }

    first_payment = iso_date(first_payment_date)
    if not first_payment:
        raise ValueError("First payment date is required.")

    duration_months = int(duration_months or 0)
    if duration_months <= 0:
        raise ValueError("Duration in months must be greater than zero.")

    monthly_payment = money(target_payment, precision) if target_payment else calculate_monthly_payment(
        opening_principal,
        annual_rate_percent,
        duration_months,
        precision,
    )
    monthly_rate = as_decimal(annual_rate_percent) / Decimal("100") / Decimal("12")
    if monthly_payment <= 0:
        raise ValueError("Monthly payment must be greater than zero.")

    balance = opening_principal
    interest_carry = Decimal("0")
    rows: list[dict] = []
    total_paid = Decimal("0")
    total_interest_paid = Decimal("0")
    scheduled_count = 0
    next_due_date = first_payment

    events = sorted(
        [event for event in (existing_events or []) if event.actual_paid_amount > 0 or event.journal_entry],
        key=lambda event: (_event_date(event), 1 if event.row_type == "Extra Payment" else 0, event.sort_index),
    )

    for event in events:
        paid_amount = money(event.actual_paid_amount, precision)
        if paid_amount <= 0:
            continue

        row_type = event.row_type or "Scheduled Payment"
        due_date = event.due_date or event.payment_date or next_due_date
        payment_date = event.payment_date or due_date

        if row_type == "Extra Payment":
            maximum_payment = balance
            if paid_amount > maximum_payment:
                raise ValueError("Extra payment cannot exceed the remaining principal balance.")

            actual_interest = Decimal("0")
            actual_principal = min(paid_amount, balance)
            scheduled_principal = Decimal("0")
            scheduled_interest = Decimal("0")
            scheduled_payment = Decimal("0")
            interest_due = interest_carry
        else:
            scheduled_count += 1
            if due_date >= next_due_date:
                next_due_date = add_months(due_date, 1)
            else:
                next_due_date = add_months(next_due_date, 1)

            interest_due = money(balance * monthly_rate + interest_carry, precision)
            maximum_payment = money(balance + interest_due, precision)
            if paid_amount > maximum_payment:
                raise ValueError("Payment cannot exceed remaining principal plus interest due.")

            scheduled_principal, scheduled_interest, scheduled_payment = _scheduled_payment_split(
                balance,
                interest_due,
                monthly_payment,
                precision,
            )
            actual_interest = min(paid_amount, interest_due)
            actual_principal = money(max(Decimal("0"), paid_amount - actual_interest), precision)
            actual_principal = min(actual_principal, balance)
            interest_carry = money(max(Decimal("0"), interest_due - actual_interest), precision)

        balance = money(balance - actual_principal, precision)
        total_paid = money(total_paid + paid_amount, precision)
        total_interest_paid = money(total_interest_paid + actual_interest, precision)

        rows.append(
            {
                "schedule_id": event.schedule_id,
                "row_type": row_type,
                "payment_number": scheduled_count if row_type != "Extra Payment" else 0,
                "due_date": due_date.isoformat() if due_date else None,
                "payment_date": payment_date.isoformat() if payment_date else None,
                "scheduled_principal": scheduled_principal,
                "scheduled_interest": scheduled_interest,
                "scheduled_payment": scheduled_payment,
                "actual_paid_amount": paid_amount,
                "actual_principal_amount": actual_principal,
                "actual_interest_amount": actual_interest,
                "interest_carry_forward": interest_carry,
                "remaining_balance": balance,
                "projected_remaining_balance": balance,
                "journal_entry": event.journal_entry,
                "payment_account": event.payment_account,
                "notes": event.notes,
            }
        )

    actual_remaining_balance = balance
    actual_interest_carry = interest_carry
    projected_balance = actual_remaining_balance
    projected_interest_carry = actual_interest_carry
    future_count = 0
    total_interest_remaining = Decimal("0")
    while projected_balance > 0 or projected_interest_carry > 0:
        future_count += 1
        if future_count > max_months:
            raise ValueError("Unable to amortize this debt within the maximum schedule length.")

        interest_due = money(projected_balance * monthly_rate + projected_interest_carry, precision)
        if projected_balance > 0 and monthly_payment <= interest_due:
            raise ValueError("Monthly payment is not high enough to cover interest and reduce principal.")

        scheduled_principal, scheduled_interest, scheduled_payment = _scheduled_payment_split(
            projected_balance,
            interest_due,
            monthly_payment,
            precision,
        )
        projected_interest_carry = money(max(Decimal("0"), interest_due - scheduled_interest), precision)
        projected_balance = money(projected_balance - scheduled_principal, precision)
        scheduled_count += 1
        total_interest_remaining = money(total_interest_remaining + scheduled_interest, precision)

        rows.append(
            {
                "schedule_id": f"SCH-{scheduled_count:04d}",
                "row_type": "Scheduled Payment",
                "payment_number": scheduled_count,
                "due_date": next_due_date.isoformat(),
                "payment_date": None,
                "scheduled_principal": scheduled_principal,
                "scheduled_interest": scheduled_interest,
                "scheduled_payment": scheduled_payment,
                "actual_paid_amount": Decimal("0"),
                "actual_principal_amount": Decimal("0"),
                "actual_interest_amount": Decimal("0"),
                "interest_carry_forward": actual_interest_carry,
                "remaining_balance": actual_remaining_balance,
                "projected_remaining_balance": projected_balance,
                "journal_entry": None,
                "payment_account": None,
                "notes": None,
            }
        )
        next_due_date = add_months(next_due_date, 1)

    maturity_date = rows[-1]["due_date"] if rows else None
    summary = {
        "monthly_payment": monthly_payment,
        "remaining_balance": actual_remaining_balance,
        "remaining_terms": future_count,
        "maturity_date": maturity_date,
        "total_paid": total_paid,
        "total_interest_paid": total_interest_paid,
        "total_interest_remaining": total_interest_remaining,
        "interest_carry_forward": actual_interest_carry,
    }
    return rows, summary
