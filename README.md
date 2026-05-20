# DebtOps

DebtOps is a Frappe/ERPNext app for managing company debt facilities, repayment schedules, actual payments, and payment Journal Entries.

The first release focuses on:

- Multi-company debt records.
- Linked liability, bank, bank account, payment, interest expense, and optional cost center accounts.
- Bank-style monthly amortization with equal target payments.
- Recalculation of the remaining schedule after underpayments, overpayments, and extra principal payments.
- Traceability from each repayment row to the Journal Entry used to record the payment.

## Core Documents

### Debt

The `Debt` DocType stores the debt header:

- Company
- Lender and optional loan/reference number
- Linked liability account
- Optional bank and bank account
- Default payment account
- Interest expense account
- Optional cost center
- Origination date and first payment date
- Annual interest rate
- Opening principal
- Original duration in months
- Calculated monthly payment
- Remaining balance and maturity date

### Debt Repayment Schedule

The child table tracks each scheduled or extra payment:

- Due date and payment date
- Scheduled principal, interest, and total payment
- Actual paid amount
- Actual principal and interest allocation
- Interest carried forward after underpayment
- Remaining balance after the row
- Linked Journal Entry

## Payment Behavior

DebtOps calculates the original target monthly payment from the opening principal, annual rate, and duration. When actual payments differ from the scheduled payment, DebtOps preserves paid rows and recalculates future rows using the same target monthly payment.

- Overpayments reduce principal faster and can shorten the schedule.
- Underpayments apply first to interest, then principal, and can extend the schedule.
- Extra payments can be recorded at any date and are treated as principal-only payments.

## Journal Entry Behavior

Payment Journal Entries are created from repayment rows:

- Debit liability account for principal paid.
- Debit interest expense account for interest paid.
- Credit payment account for total paid.
- Apply the optional cost center to the interest line.

## Install

From your Frappe bench:

```bash
bench get-app https://github.com/YOUR-ORG/YOUR-REPO.git
bench --site YOUR-SITE install-app debtops
bench --site YOUR-SITE migrate
```

Replace the GitHub URL and site name with your actual values.

## Development

The amortization engine is kept in a pure Python module so it can be tested without a running Frappe site:

```bash
python -m unittest discover debtops/tests
```

