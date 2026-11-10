# Data dictionary

All money is in Indian rupees. All data is synthetic.

## Dimensions

### dim_date
Calendar from 1 Jan 2025 to 31 Dec 2026. `date_key` is `yyyymmdd`. `fiscal_year` follows the Indian financial year (April to March, so Nov 2026 is FY27). `fiscal_quarter`: Q1 is April to June.

### dim_client
| Column | Meaning |
|---|---|
| client_key | surrogate key |
| client_id | business key from the billing system |
| industry | standardised to Title Case; `Unknown` when the source was blank |
| payment_terms_days | contractual terms: 30, 45 or 60 |
| tier | Strategic, Key or Standard |

### dim_project
One row per engagement. `billing_type` is Time & Materials or Fixed Fee. `budget_hours` is the approved effort used for budget burn.

### dim_employee (slowly changing dimension, type 2)
One row per employee per grade. A promotion closes the old row (`valid_to` = promotion date, exclusive) and opens a new one. `is_current = 1` marks today's version. Facts point at the version that applied on the day of work, so a promotion never rewrites history.

| Column | Meaning |
|---|---|
| employee_key | surrogate key of this version |
| employee_id | business key, shared by all versions of one person |
| grade, bill_rate, cost_rate | values valid between `valid_from` and `valid_to` |

## Facts

### fact_timesheet (grain: one timesheet line)
`standard_value` = billable hours × bill rate on the day. `cost_value` = all hours × cost rate on the day. `billable_hours` is 0 for non-billable lines.

### fact_invoice (grain: one invoice, billed monthly per project)
`billing_period` is the month of work being billed, in `yyyy-mm`. It lets the WIP view find months that have not been billed.

### fact_payment (grain: one receipt)
One invoice can have several receipts (part payments).

## Reporting views

| View | Grain | Purpose |
|---|---|---|
| vw_utilization_monthly | employee × month | billable hours ÷ available hours (weekdays × 8) |
| vw_project_profitability | project | standard value, invoiced, collected, delivery margin, budget burn, realization |
| vw_ar_ageing | open invoice | outstanding amount and ageing bucket at the reporting date |
| vw_client_scorecard | client | billing, collections, overdue, average days to pay and days late |
| vw_wip_unbilled | project × month | billable work with no invoice yet |
| vw_monthly_financials | month | invoiced, collected, cost, hours |

## Metric definitions

| Metric | Formula |
|---|---|
| Utilization | billable hours ÷ (weekdays in month × 8). Public holidays are not removed. |
| Realization | invoiced ÷ standard value of the billable hours |
| Delivery margin | invoiced − delivery cost. It excludes overheads, so it is higher than a firm-level margin. |
| Budget burn | hours logged ÷ budget hours |
| Days past due | reporting date − due date |
| DSO | outstanding receivables ÷ (invoiced in the last 90 days ÷ 90) |

## Data quality rule ids

C = clients, P = projects, E = employee history, T = timesheets, I = invoices, Y = payments, R = post-load reconciliation. The full list with counts is written to `output/dq_report.md` on every run.
