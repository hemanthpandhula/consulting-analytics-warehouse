# Data quality report

Reporting date: 2026-10-31

## Reconciliation

| Table | Rows read | Duplicates removed | Quarantined | Loaded |
|---|---:|---:|---:|---:|
| clients | 32 | 2 | 0 | 30 |
| projects | 80 | 0 | 0 | 80 |
| timesheets | 21,266 | 252 | 513 | 20,501 |
| invoices | 594 | 6 | 2 | 586 |
| payments | 549 | 5 | 5 | 539 |

## Rules

| Rule | Table | What it checks | Rows checked | Rows failed | Action | Severity | Status |
|---|---|---|---:|---:|---|---|---|
| C01 | clients | client_id appears more than once | 32 | 2 | keep first, drop the rest | warning | info |
| C02 | clients | industry blank | 30 | 2 | set to 'Unknown' | warning | info |
| C03 | clients | industry written in mixed case | 30 | 5 | standardise to Title Case | warning | info |
| P01 | projects | project dates not ISO (dd/mm/yyyy) | 80 | 25 | parse and convert | warning | info |
| P02 | projects | project references an unknown client | 80 | 0 | quarantine | critical | info |
| P03 | projects | end_date before start_date or unreadable date | 80 | 0 | quarantine | critical | info |
| E01 | employee_grade_history | first grade record does not start on the hire date | 60 | 0 | report only | warning | info |
| T01 | timesheets | timesheet_id appears more than once | 21,266 | 252 | keep first, drop the rest | warning | info |
| T02 | timesheets | hours missing or not a number | 21,014 | 81 | quarantine | critical | info |
| T03 | timesheets | hours <= 0 or > 16 | 20,933 | 116 | quarantine | critical | info |
| T04 | timesheets | employee_id not found in HR | 20,817 | 114 | quarantine | critical | info |
| T05 | timesheets | project_id not found in projects | 20,703 | 94 | quarantine | critical | info |
| T06 | timesheets | work_date unreadable or after the reporting date | 20,609 | 59 | quarantine | critical | info |
| T07 | timesheets | work_date before the employee's hire date | 20,550 | 49 | quarantine | critical | info |
| T08 | timesheets | ids with stray case or whitespace | 21,014 | 434 | trim and upper-case | warning | info |
| T09 | timesheets | billable flag written in a non-standard way (y, Yes, TRUE, 1 ...) | 20,501 | 11,954 | map to Y / N | warning | info |
| T10 | timesheets | work_date not ISO (dd/mm/yyyy) | 21,014 | 2,577 | parse and convert | warning | info |
| I01 | invoices | invoice_id appears more than once | 594 | 6 | keep first, drop the rest | warning | info |
| I02 | invoices | client_id blank | 588 | 1 | back-fill from the project | warning | info |
| I03 | invoices | client_id differs from the project's client | 588 | 0 | quarantine | critical | info |
| I04 | invoices | amount stored as text with commas | 588 | 12 | strip commas and convert | warning | info |
| I05 | invoices | due_date before invoice_date or unreadable date | 588 | 2 | quarantine | critical | info |
| I06 | invoices | amount <= 0 or not a number | 588 | 0 | quarantine | critical | info |
| I07 | invoices | project_id not found in projects | 588 | 0 | quarantine | critical | info |
| Y01 | payments | payment_id appears more than once | 549 | 5 | keep first, drop the rest | warning | info |
| Y02 | payments | invoice_id not found in invoices | 544 | 5 | quarantine | critical | info |
| Y03 | payments | amount <= 0 or not a number | 539 | 0 | quarantine | critical | info |
| Y04 | payments | paid_date unreadable, before the invoice date or after the reporting date | 539 | 0 | quarantine | critical | info |
| R01 | warehouse | rows read = rows loaded + quarantined + duplicates removed (every table) | 22,521 | 0 | must be zero gap | critical | pass |
| R02 | warehouse | fact tables have no foreign key pointing at a missing dimension row | 7 | 0 | must be zero | critical | pass |
| R03 | warehouse | employee versions never overlap and leave no gap (SCD type 2) | 60 | 0 | must be zero | critical | pass |
| R04 | warehouse | invoice total in the warehouse equals the cleaned invoice total | 1 | 0 | difference < 1 rupee | critical | pass |
| R05 | warehouse | standard value in fact_timesheet equals hours x the bill rate valid on the day | 1 | 0 | difference < 1 rupee | critical | pass |
| R06 | warehouse | no payment is dated before its invoice | 539 | 0 | must be zero | critical | pass |
| R07 | warehouse | no invoice is paid more than its amount | 586 | 0 | must be zero | critical | pass |

Rows that fail a *quarantine* rule are not loaded. They are kept in the `dq_quarantine` table with the rule id and the full source row, so a data owner can correct them at source.
