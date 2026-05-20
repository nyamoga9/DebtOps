import frappe


def execute():
    if not frappe.db.table_exists("Debt") or not frappe.db.table_exists("Debt Repayment Schedule"):
        return

    for debt in frappe.get_all("Debt", fields=["name", "currency"]):
        if not debt.currency:
            continue

        frappe.db.sql(
            """
            update `tabDebt Repayment Schedule`
            set currency = %s
            where parent = %s
                and (currency is null or currency = '')
            """,
            (debt.currency, debt.name),
        )
