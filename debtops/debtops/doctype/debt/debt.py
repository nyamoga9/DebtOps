from decimal import Decimal

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, flt, getdate, nowdate

from debtops.debtops.doctype.debt.schedule import PaymentEvent, build_repayment_schedule


class Debt(Document):
    def validate(self):
        self.set_defaults()
        self.validate_accounts()
        self.recalculate_schedule()

    def set_defaults(self):
        if not self.first_payment_date and self.origination_date:
            self.first_payment_date = add_months(self.origination_date, 1)
        if self.company and not self.currency:
            self.currency = frappe.db.get_value("Company", self.company, "default_currency")
        if not self.status:
            self.status = "Active"

    def validate_accounts(self):
        expected_root_types = {
            "liability_account": ("Liability",),
            "interest_expense_account": ("Expense",),
            "default_payment_account": ("Asset",),
        }
        for fieldname, root_types in expected_root_types.items():
            account = self.get(fieldname)
            if not account:
                continue
            self.validate_account(account, self.meta.get_label(fieldname), root_types)

        for row in self.repayment_schedule or []:
            if row.payment_account:
                self.validate_account(row.payment_account, _("Payment Account"), ("Asset",))

        if self.cost_center:
            cost_center_company = frappe.db.get_value("Cost Center", self.cost_center, "company")
            if cost_center_company and self.company and cost_center_company != self.company:
                frappe.throw(_("Cost Center must belong to company {0}.").format(self.company))

    def validate_account(self, account, label, allowed_root_types):
        account_details = frappe.db.get_value("Account", account, ["company", "is_group", "root_type"], as_dict=True)
        if not account_details:
            frappe.throw(_("{0} {1} was not found.").format(label, account))
        if account_details.is_group:
            frappe.throw(_("{0} must be a ledger account.").format(label))
        if account_details.company and self.company and account_details.company != self.company:
            frappe.throw(_("{0} must belong to company {1}.").format(label, self.company))
        if allowed_root_types and account_details.root_type not in allowed_root_types:
            frappe.throw(
                _("{0} must be a {1} account.").format(label, _(" or ").join(allowed_root_types))
            )

    def recalculate_schedule(self):
        if not self.opening_principal or not self.original_duration_months or not self.first_payment_date:
            self.set("repayment_schedule", [])
            self.remaining_balance = flt(self.opening_principal)
            return

        events = self.get_payment_events()
        target_payment = flt(self.payment_amount_override) or None

        try:
            rows, summary = build_repayment_schedule(
                principal=self.opening_principal,
                annual_rate_percent=self.interest_rate_percent or 0,
                duration_months=self.original_duration_months,
                first_payment_date=getdate(self.first_payment_date),
                existing_events=events,
                target_payment=target_payment,
                precision=2,
            )
        except ValueError as exc:
            frappe.throw(str(exc))

        self.set("repayment_schedule", [])
        for row in rows:
            self.append(
                "repayment_schedule",
                {
                    "schedule_id": row["schedule_id"],
                    "row_type": row["row_type"],
                    "payment_number": row["payment_number"],
                    "due_date": row["due_date"],
                    "payment_date": row["payment_date"],
                    "currency": self.currency,
                    "scheduled_principal": flt(row["scheduled_principal"]),
                    "scheduled_interest": flt(row["scheduled_interest"]),
                    "scheduled_payment": flt(row["scheduled_payment"]),
                    "actual_paid_amount": flt(row["actual_paid_amount"]),
                    "actual_principal_amount": flt(row["actual_principal_amount"]),
                    "actual_interest_amount": flt(row["actual_interest_amount"]),
                    "interest_carry_forward": flt(row["interest_carry_forward"]),
                    "remaining_balance": flt(row["remaining_balance"]),
                    "projected_remaining_balance": flt(row["projected_remaining_balance"]),
                    "journal_entry": row["journal_entry"],
                    "payment_account": row["payment_account"],
                    "notes": row["notes"],
                },
            )

        self.monthly_payment = flt(summary["monthly_payment"])
        self.remaining_balance = flt(summary["remaining_balance"])
        self.remaining_terms = summary["remaining_terms"]
        self.maturity_date = summary["maturity_date"]
        self.total_paid = flt(summary["total_paid"])
        self.total_interest_paid = flt(summary["total_interest_paid"])
        self.total_interest_remaining = flt(summary["total_interest_remaining"])
        self.interest_carry_forward = flt(summary["interest_carry_forward"])
        self.status = "Paid Off" if flt(self.remaining_balance) == 0 and flt(self.interest_carry_forward) == 0 else "Active"

    def get_payment_events(self):
        events = []
        for index, row in enumerate(self.repayment_schedule or [], start=1):
            actual_paid_amount = Decimal(str(flt(row.actual_paid_amount)))
            row_type = row.row_type or "Scheduled Payment"
            is_recorded_zero_payment = (
                row_type != "Extra Payment"
                and actual_paid_amount == 0
                and row.payment_date
            )
            if actual_paid_amount <= 0 and not row.journal_entry and not is_recorded_zero_payment:
                continue
            events.append(
                PaymentEvent(
                    schedule_id=row.schedule_id or row.name,
                    row_type=row_type,
                    due_date=getdate(row.due_date) if row.due_date else None,
                    payment_date=getdate(row.payment_date) if row.payment_date else None,
                    actual_paid_amount=actual_paid_amount,
                    journal_entry=row.journal_entry,
                    payment_account=row.payment_account,
                    notes=row.notes,
                    sort_index=index,
                )
            )
        return events

    def get_schedule_row(self, schedule_id):
        for row in self.repayment_schedule or []:
            if row.schedule_id == schedule_id:
                return row
        frappe.throw(_("Repayment schedule row {0} was not found.").format(schedule_id))


@frappe.whitelist()
def recalculate_debt_schedule(debt):
    doc = frappe.get_doc("Debt", debt)
    doc.recalculate_schedule()
    doc.save()
    return {"debt": doc.name, "remaining_balance": doc.remaining_balance, "maturity_date": doc.maturity_date}


@frappe.whitelist()
def create_payment_journal_entry(
    debt,
    schedule_id,
    paid_amount=None,
    payment_account=None,
    posting_date=None,
    submit=1,
):
    doc = frappe.get_doc("Debt", debt)
    row = doc.get_schedule_row(schedule_id)
    if row.journal_entry:
        frappe.throw(_("Repayment row {0} already has Journal Entry {1}.").format(schedule_id, row.journal_entry))

    has_paid_amount = paid_amount is not None and paid_amount != ""
    amount = flt(paid_amount) if has_paid_amount else flt(row.actual_paid_amount) or flt(row.scheduled_payment)
    if amount < 0:
        frappe.throw(_("Paid amount cannot be negative."))

    if amount == 0:
        row.currency = doc.currency
        row.actual_paid_amount = 0
        row.payment_date = posting_date or row.payment_date or nowdate()
        doc.save()
        return {
            "debt": doc.name,
            "schedule_id": schedule_id,
            "missed_payment": 1,
            "remaining_balance": doc.remaining_balance,
            "maturity_date": doc.maturity_date,
        }

    row.currency = doc.currency
    row.actual_paid_amount = amount
    row.payment_date = posting_date or row.payment_date or nowdate()
    row.payment_account = payment_account or row.payment_account or doc.default_payment_account
    if not row.payment_account:
        frappe.throw(_("Payment account is required."))

    doc.recalculate_schedule()
    row = doc.get_schedule_row(schedule_id)
    journal_entry = _make_payment_journal_entry(doc, row, submit=submit)
    row.journal_entry = journal_entry.name
    row.payment_account = payment_account or row.payment_account or doc.default_payment_account
    doc.save()

    return {"journal_entry": journal_entry.name, "debt": doc.name, "schedule_id": schedule_id}


@frappe.whitelist()
def create_extra_payment_journal_entry(
    debt,
    paid_amount,
    payment_account=None,
    posting_date=None,
    notes=None,
    submit=1,
):
    doc = frappe.get_doc("Debt", debt)
    payment_account = payment_account or doc.default_payment_account
    if not payment_account:
        frappe.throw(_("Payment account is required."))

    schedule_id = "EXT-" + frappe.generate_hash(length=10).upper()
    doc.append(
        "repayment_schedule",
        {
            "schedule_id": schedule_id,
            "row_type": "Extra Payment",
            "due_date": posting_date or nowdate(),
            "payment_date": posting_date or nowdate(),
            "currency": doc.currency,
            "actual_paid_amount": paid_amount,
            "payment_account": payment_account,
            "notes": notes,
        },
    )
    doc.save()
    return create_payment_journal_entry(
        debt=doc.name,
        schedule_id=schedule_id,
        paid_amount=paid_amount,
        payment_account=payment_account,
        posting_date=posting_date or nowdate(),
        submit=submit,
    )


def _make_payment_journal_entry(debt_doc, schedule_row, submit=1):
    paid_amount = flt(schedule_row.actual_paid_amount)
    principal_amount = flt(schedule_row.actual_principal_amount)
    interest_amount = flt(schedule_row.actual_interest_amount)
    payment_account = schedule_row.payment_account or debt_doc.default_payment_account

    if paid_amount <= 0:
        frappe.throw(_("Paid amount must be greater than zero."))
    if principal_amount <= 0 and interest_amount <= 0:
        frappe.throw(_("Payment did not allocate to principal or interest."))
    if interest_amount > 0 and not debt_doc.interest_expense_account:
        frappe.throw(_("Interest Expense Account is required when a payment includes interest."))
    if not payment_account:
        frappe.throw(_("Payment account is required."))

    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Bank Entry"
    je.company = debt_doc.company
    je.multi_currency = 1 if journal_entry_uses_multi_currency(debt_doc, payment_account) else 0
    je.posting_date = schedule_row.payment_date or nowdate()
    reference_date = schedule_row.payment_date or nowdate()
    reference_no = get_payment_reference_no(debt_doc, schedule_row)
    if je.meta.has_field("cheque_no"):
        je.cheque_no = reference_no
    if je.meta.has_field("cheque_date"):
        je.cheque_date = reference_date
    if je.meta.has_field("reference_no"):
        je.reference_no = reference_no
    if je.meta.has_field("reference_date"):
        je.reference_date = reference_date
    je.user_remark = _("Debt payment for {0}, row {1}").format(debt_doc.name, schedule_row.schedule_id)

    if principal_amount:
        je.append(
            "accounts",
            {
                "account": debt_doc.liability_account,
                "debit_in_account_currency": principal_amount,
                "debit": principal_amount,
            },
        )

    if interest_amount:
        je.append(
            "accounts",
            {
                "account": debt_doc.interest_expense_account,
                "debit_in_account_currency": interest_amount,
                "debit": interest_amount,
                "cost_center": debt_doc.cost_center,
            },
        )

    je.append(
        "accounts",
        {
            "account": payment_account,
            "credit_in_account_currency": paid_amount,
            "credit": paid_amount,
        },
    )
    je.insert()
    if int(submit):
        je.submit()
    return je


def journal_entry_uses_multi_currency(debt_doc, payment_account):
    company_currency = frappe.db.get_value("Company", debt_doc.company, "default_currency")
    accounts = [
        debt_doc.liability_account,
        debt_doc.interest_expense_account,
        payment_account,
    ]
    account_currencies = frappe.get_all(
        "Account",
        filters={"name": ("in", [account for account in accounts if account])},
        pluck="account_currency",
    )
    currencies = {currency for currency in account_currencies if currency}
    currencies.add(debt_doc.currency)
    return any(currency and currency != company_currency for currency in currencies)


def get_payment_reference_no(debt_doc, schedule_row):
    schedule_id = schedule_row.schedule_id or schedule_row.name
    due_date = schedule_row.due_date or schedule_row.payment_date
    parts = [debt_doc.loan_reference_number or debt_doc.debt_name or debt_doc.name]
    if schedule_id:
        parts.append(schedule_id)
    if due_date:
        parts.append(str(due_date))
    return " / ".join(parts)
