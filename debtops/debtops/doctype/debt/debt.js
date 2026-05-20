frappe.ui.form.on("Debt", {
    setup(frm) {
        const accountQuery = (extraFilters = {}) => ({
            filters: {
                company: frm.doc.company,
                is_group: 0,
                ...extraFilters,
            },
        });

        frm.set_query("liability_account", () => accountQuery({ root_type: "Liability" }));
        frm.set_query("interest_expense_account", () => accountQuery({ root_type: "Expense" }));
        frm.set_query("default_payment_account", () => accountQuery({ root_type: "Asset" }));

        frm.set_query("payment_account", "repayment_schedule", () => accountQuery({ root_type: "Asset" }));

        frm.set_query("cost_center", () => ({
            filters: {
                company: frm.doc.company,
                is_group: 0,
            },
        }));

        frm.set_query("bank_account", () => ({
            filters: {
                company: frm.doc.company,
            },
        }));
    },

    refresh(frm) {
        sync_schedule_currency(frm);

        if (frm.is_new()) {
            return;
        }

        frm.add_custom_button(__("Recalculate Schedule"), () => {
            frappe.call({
                method: "debtops.debtops.doctype.debt.debt.recalculate_debt_schedule",
                args: {
                    debt: frm.doc.name,
                },
                freeze: true,
                freeze_message: __("Recalculating schedule..."),
                callback() {
                    frm.reload_doc();
                },
            });
        });

        frm.add_custom_button(__("Create Payment JE"), () => {
            show_payment_dialog(frm);
        }, __("Payments"));

        frm.add_custom_button(__("Add Extra Payment"), () => {
            show_extra_payment_dialog(frm);
        }, __("Payments"));
    },

    currency(frm) {
        sync_schedule_currency(frm);
        frm.refresh_field("repayment_schedule");
    },
});

function sync_schedule_currency(frm) {
    (frm.doc.repayment_schedule || []).forEach((row) => {
        row.currency = frm.doc.currency;
    });
}

function unpaid_schedule_options(frm) {
    return (frm.doc.repayment_schedule || [])
        .filter((row) => row.row_type !== "Extra Payment" && !row.journal_entry)
        .map((row) => {
            const amount = format_currency(row.scheduled_payment, frm.doc.currency);
            return {
                label: `${row.payment_number || row.idx} | ${row.due_date || ""} | ${amount}`,
                value: row.schedule_id,
            };
        });
}

function show_payment_dialog(frm) {
    const rows = unpaid_schedule_options(frm);
    if (!rows.length) {
        frappe.msgprint(__("There are no unpaid scheduled rows."));
        return;
    }

    const defaultRow = rows[0].value;
    const scheduleRow = (frm.doc.repayment_schedule || []).find((row) => row.schedule_id === defaultRow);

    const dialog = new frappe.ui.Dialog({
        title: __("Create Payment Journal Entry"),
        fields: [
            {
                fieldname: "schedule_id",
                fieldtype: "Select",
                label: __("Repayment Row"),
                options: rows,
                default: defaultRow,
                reqd: 1,
            },
            {
                fieldname: "posting_date",
                fieldtype: "Date",
                label: __("Posting Date"),
                default: frappe.datetime.get_today(),
                reqd: 1,
            },
            {
                fieldname: "paid_amount",
                fieldtype: "Currency",
                label: __("Paid Amount"),
                options: frm.doc.currency,
                default: scheduleRow ? scheduleRow.scheduled_payment : 0,
                description: __("Enter 0 to record a missed payment without creating a Journal Entry."),
            },
            {
                fieldname: "payment_account",
                fieldtype: "Link",
                label: __("Payment Account"),
                options: "Account",
                default: frm.doc.default_payment_account,
                description: __("Required when Paid Amount is greater than 0."),
                get_query: () => ({
                    filters: {
                        company: frm.doc.company,
                        is_group: 0,
                        root_type: "Asset",
                    },
                }),
            },
            {
                fieldname: "submit",
                fieldtype: "Check",
                label: __("Submit Journal Entry"),
                default: 1,
            },
        ],
        primary_action_label: __("Create"),
        primary_action(values) {
            frappe.call({
                method: "debtops.debtops.doctype.debt.debt.create_payment_journal_entry",
                args: {
                    debt: frm.doc.name,
                    schedule_id: values.schedule_id,
                    paid_amount: values.paid_amount,
                    payment_account: values.payment_account,
                    posting_date: values.posting_date,
                    submit: values.submit ? 1 : 0,
                },
                freeze: true,
                freeze_message: __("Recording payment..."),
                callback(response) {
                    dialog.hide();
                    if (response.message && response.message.journal_entry) {
                        frappe.set_route("Form", "Journal Entry", response.message.journal_entry);
                    } else if (response.message && response.message.missed_payment) {
                        frappe.msgprint(__("Missed payment recorded. The debt schedule was recalculated."));
                        frm.reload_doc();
                    } else {
                        frm.reload_doc();
                    }
                },
            });
        },
    });

    dialog.fields_dict.schedule_id.$input.on("change", () => {
        const selected = dialog.get_value("schedule_id");
        const row = (frm.doc.repayment_schedule || []).find((item) => item.schedule_id === selected);
        if (row) {
            dialog.set_value("paid_amount", row.scheduled_payment);
        }
    });

    dialog.show();
}

function show_extra_payment_dialog(frm) {
    const dialog = new frappe.ui.Dialog({
        title: __("Add Extra Payment"),
        fields: [
            {
                fieldname: "posting_date",
                fieldtype: "Date",
                label: __("Posting Date"),
                default: frappe.datetime.get_today(),
                reqd: 1,
            },
            {
                fieldname: "paid_amount",
                fieldtype: "Currency",
                label: __("Paid Amount"),
                options: frm.doc.currency,
                reqd: 1,
            },
            {
                fieldname: "payment_account",
                fieldtype: "Link",
                label: __("Payment Account"),
                options: "Account",
                default: frm.doc.default_payment_account,
                reqd: 1,
                get_query: () => ({
                    filters: {
                        company: frm.doc.company,
                        is_group: 0,
                        root_type: "Asset",
                    },
                }),
            },
            {
                fieldname: "notes",
                fieldtype: "Small Text",
                label: __("Notes"),
            },
            {
                fieldname: "submit",
                fieldtype: "Check",
                label: __("Submit Journal Entry"),
                default: 1,
            },
        ],
        primary_action_label: __("Create"),
        primary_action(values) {
            frappe.call({
                method: "debtops.debtops.doctype.debt.debt.create_extra_payment_journal_entry",
                args: {
                    debt: frm.doc.name,
                    paid_amount: values.paid_amount,
                    payment_account: values.payment_account,
                    posting_date: values.posting_date,
                    notes: values.notes,
                    submit: values.submit ? 1 : 0,
                },
                freeze: true,
                freeze_message: __("Creating Journal Entry..."),
                callback(response) {
                    dialog.hide();
                    if (response.message && response.message.journal_entry) {
                        frappe.set_route("Form", "Journal Entry", response.message.journal_entry);
                    } else {
                        frm.reload_doc();
                    }
                },
            });
        },
    });
    dialog.show();
}
