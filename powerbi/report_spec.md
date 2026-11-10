# Power BI report: build guide (about 90 minutes)

This repository ships the **data model, the measures and the page design** for a Power BI report, not a `.pbix` file. A `.pbix` can only be created in Power BI Desktop (free, Windows). Build it once from this guide, publish a screenshot or a PDF export to your profile, and only then describe it as a Power BI project.

## 1. Load the data

1. Run `python run_pipeline.py` so `output/marts/` is filled.
2. In Power BI Desktop choose **Get data → Text/CSV** and load these files: `dim_date`, `dim_client`, `dim_project`, `dim_employee`, `fact_timesheet`, `fact_invoice`, `fact_payment`, `vw_utilization_monthly`, `vw_project_profitability`, `vw_ar_ageing`, `vw_client_scorecard`, `vw_wip_unbilled`, `vw_monthly_financials`.
3. In Power Query set types: `dim_date[date]` to **Date**; every `*_key` column to **Whole number**; money and hours columns to **Decimal number**.
4. Select `dim_date`, then **Table tools → Mark as date table** using the `date` column.

## 2. Model (star schema, single-direction filters)

| From (many) | To (one) | Active |
|---|---|---|
| fact_timesheet[date_key] | dim_date[date_key] | yes |
| fact_timesheet[employee_key] | dim_employee[employee_key] | yes |
| fact_timesheet[project_key] | dim_project[project_key] | yes |
| dim_project[client_key] | dim_client[client_key] | yes |
| fact_invoice[invoice_date_key] | dim_date[date_key] | yes |
| fact_invoice[due_date_key] | dim_date[date_key] | no (use `USERELATIONSHIP` if needed) |
| fact_invoice[client_key] | dim_client[client_key] | yes |
| fact_invoice[project_key] | dim_project[project_key] | yes |
| fact_payment[paid_date_key] | dim_date[date_key] | yes |
| fact_payment[client_key] | dim_client[client_key] | yes |

The `vw_*` tables are already shaped for reporting. Use them as stand-alone tables on their pages and filter them with slicers built from their own columns (for example `practice`, `client_name`).

## 3. Measures

Create a table called `_Measures` (Home → Enter data, one blank column), then paste each measure from `measures.dax`.

## 4. Pages

| Page | Question it answers | Visuals |
|---|---|---|
| **1. Practice overview** | How is the practice doing? | Cards: Invoiced, Delivery Margin %, Utilization %, Realization %. Line: monthly invoiced against collected (`vw_monthly_financials`). Clustered bar: margin % by practice. Slicers: fiscal year, practice. |
| **2. Utilization** | Who is over or under used? | Heat-map matrix: employee by month, value `utilization_pct`, colour scale red to green. Column: utilization by practice. Table: lowest 10 over the last 3 months. |
| **3. Project health** | Which projects lose money or overrun? | Scatter: x `budget_burn_pct`, y `margin_pct`, size `invoiced`. Table with conditional-format data bars on `margin_pct`. Slicer: billing type. |
| **4. Receivables** | Who do we chase first? | Stacked column: outstanding by ageing bucket. Bar: overdue by client. Cards: DSO, Overdue %, Over 90 Days AR. Table of open invoices sorted by `days_past_due`. Tooltip page with client history. |

## 5. Finishing touches that interviewers notice

- A navigation bar with page buttons, and a **Reset filters** bookmark.
- Consistent colour: one colour for good, one for bad, grey for everything else.
- Dynamic title on page 1 using the `Margin Title` measure.
- Row-level security idea to mention: a `practice` role that filters `dim_employee[practice]` and `dim_project[practice]`.
- Add a one-line takeaway under each page title, written as a finding (for example, "Three clients hold 71% of overdue cash").

## 6. Check your numbers

Cross-check against SQL before you publish:

| Measure | Should match |
|---|---|
| Overdue AR | `SELECT SUM(outstanding) FROM vw_ar_ageing WHERE days_past_due > 0` |
| Delivery Margin % | `output/business_summary.md` |
| Utilization % (2026) | `output/business_summary.md` |
