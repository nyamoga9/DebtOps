import frappe
from frappe import _


def execute(filters=None):
    columns = [
        {"fieldname": "name", "label": _("Debt"), "fieldtype": "Link", "options": "Debt", "width": 160},
        {"fieldname": "debt_name", "label": _("Debt Name"), "fieldtype": "Data", "width": 200},
        {"fieldname": "company", "label": _("Company"), "fieldtype": "Link", "options": "Company", "width": 180},
        {"fieldname": "lender_name", "label": _("Lender"), "fieldtype": "Data", "width": 160},
        {"fieldname": "interest_rate_percent", "label": _("Rate %"), "fieldtype": "Percent", "width": 90},
        {"fieldname": "monthly_payment", "label": _("Monthly Payment"), "fieldtype": "Currency", "width": 140},
        {"fieldname": "remaining_balance", "label": _("Remaining Balance"), "fieldtype": "Currency", "width": 150},
        {"fieldname": "remaining_terms", "label": _("Remaining Terms"), "fieldtype": "Int", "width": 120},
        {"fieldname": "maturity_date", "label": _("Projected Maturity"), "fieldtype": "Date", "width": 140},
        {"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
    ]

    data = frappe.get_all(
        "Debt",
        fields=[
            "name",
            "debt_name",
            "company",
            "lender_name",
            "interest_rate_percent",
            "monthly_payment",
            "remaining_balance",
            "remaining_terms",
            "maturity_date",
            "status",
        ],
        order_by="company, lender_name, maturity_date",
    )
    return columns, data

