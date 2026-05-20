from frappe import _


def get_data():
    return [
        {
            "module_name": "DebtOps",
            "type": "module",
            "label": _("DebtOps"),
            "color": "#0f766e",
            "icon": "/assets/debtops/images/debtops.svg",
        }
    ]
