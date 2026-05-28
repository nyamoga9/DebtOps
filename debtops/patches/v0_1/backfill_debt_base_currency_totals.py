import frappe
from frappe.utils import flt, nowdate
from erpnext.setup.utils import get_exchange_rate


def execute():
    update_dashboard_documents()
    required_columns = {
        "company_currency",
        "base_exchange_rate",
        "base_opening_principal",
        "base_monthly_payment",
        "base_remaining_balance",
        "base_total_interest_remaining",
    }
    if not all(frappe.db.has_column("Debt", column) for column in required_columns):
        return

    debts = frappe.get_all(
        "Debt",
        fields=[
            "name",
            "company",
            "currency",
            "opening_principal",
            "monthly_payment",
            "remaining_balance",
            "total_interest_remaining",
        ],
    )

    for debt in debts:
        company_currency = (
            frappe.db.get_value("Company", debt.company, "default_currency")
            if debt.company
            else debt.currency
        )
        rate = 1
        if debt.currency and company_currency and debt.currency != company_currency:
            rate = get_exchange_rate(debt.currency, company_currency, nowdate()) or 0

        frappe.db.set_value(
            "Debt",
            debt.name,
            {
                "company_currency": company_currency,
                "base_exchange_rate": flt(rate),
                "base_opening_principal": flt(debt.opening_principal) * flt(rate),
                "base_monthly_payment": flt(debt.monthly_payment) * flt(rate),
                "base_remaining_balance": flt(debt.remaining_balance) * flt(rate),
                "base_total_interest_remaining": flt(debt.total_interest_remaining) * flt(rate),
            },
            update_modified=False,
        )


def update_dashboard_documents():
    number_cards = {
        "Total Debt Outstanding": "base_remaining_balance",
        "Monthly Debt Payments": "base_monthly_payment",
        "Projected Interest Remaining": "base_total_interest_remaining",
    }
    for card, fieldname in number_cards.items():
        if frappe.db.exists("Number Card", card):
            frappe.db.set_value(
                "Number Card",
                card,
                "aggregate_function_based_on",
                fieldname,
                update_modified=False,
            )

    if frappe.db.exists("Dashboard Chart", "Debt Originations"):
        frappe.db.set_value(
            "Dashboard Chart",
            "Debt Originations",
            "value_based_on",
            "base_opening_principal",
            update_modified=False,
        )
