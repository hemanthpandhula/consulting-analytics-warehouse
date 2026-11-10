-- Reporting layer. These views are what Power BI / Tableau read, so business logic lives in one place.
-- The reporting date comes from etl_config so every number is reproducible.

-- 1) Utilization by employee and month: billable hours / available hours (weekdays x 8)
CREATE VIEW vw_utilization_monthly AS
WITH months AS (
  SELECT year, month, MIN(date) AS month_start,
         SUM(CASE WHEN is_weekend = 0 THEN 1 ELSE 0 END) AS working_days
  FROM dim_date
  WHERE date <= (SELECT as_of_date FROM etl_config)
  GROUP BY year, month
),
emp AS (
  SELECT employee_id, MIN(valid_from) AS hire_date FROM dim_employee GROUP BY employee_id
),
current_emp AS (
  SELECT employee_id, full_name, practice, location FROM dim_employee WHERE is_current = 1
),
spine AS (
  SELECT e.employee_id, m.year, m.month, m.month_start, m.working_days
  FROM emp e
  JOIN months m ON m.month_start >= date(e.hire_date, 'start of month')
),
hrs AS (
  SELECT e.employee_id, d.year, d.month,
         SUM(f.hours) AS total_hours, SUM(f.billable_hours) AS billable_hours
  FROM fact_timesheet f
  JOIN dim_date d     ON d.date_key = f.date_key
  JOIN dim_employee e ON e.employee_key = f.employee_key
  GROUP BY e.employee_id, d.year, d.month
)
SELECT s.employee_id, c.full_name, c.practice, c.location,
       s.year, s.month, s.month_start,
       s.working_days * 8                                           AS capacity_hours,
       COALESCE(h.total_hours, 0)                                   AS total_hours,
       COALESCE(h.billable_hours, 0)                                AS billable_hours,
       ROUND(COALESCE(h.billable_hours, 0) * 100.0 / (s.working_days * 8), 1) AS utilization_pct
FROM spine s
JOIN current_emp c ON c.employee_id = s.employee_id
LEFT JOIN hrs h    ON h.employee_id = s.employee_id AND h.year = s.year AND h.month = s.month;

-- 2) Project profitability: value of work at standard rates, cost, margin, budget burn, realization
CREATE VIEW vw_project_profitability AS
WITH t AS (
  SELECT project_key, SUM(hours) AS hours, SUM(billable_hours) AS billable_hours,
         SUM(standard_value) AS standard_value, SUM(cost_value) AS cost_value
  FROM fact_timesheet GROUP BY project_key
),
i AS (
  SELECT project_key, SUM(amount) AS invoiced FROM fact_invoice GROUP BY project_key
),
p AS (
  SELECT i.project_key, SUM(pay.amount) AS collected
  FROM fact_payment pay JOIN fact_invoice i ON i.invoice_key = pay.invoice_key GROUP BY i.project_key
)
SELECT dp.project_id, dp.project_name, dc.client_name, dp.practice, dp.billing_type,
       ROUND(t.hours, 1)                                        AS hours,
       dp.budget_hours,
       ROUND(t.hours * 100.0 / dp.budget_hours, 1)               AS budget_burn_pct,
       ROUND(t.standard_value)                                  AS standard_value,
       ROUND(COALESCE(i.invoiced, 0))                           AS invoiced,
       ROUND(COALESCE(p.collected, 0))                          AS collected,
       ROUND(t.cost_value)                                      AS cost_value,
       ROUND(COALESCE(i.invoiced, 0) - t.cost_value)            AS margin,
       ROUND((COALESCE(i.invoiced, 0) - t.cost_value) * 100.0 / NULLIF(i.invoiced, 0), 1) AS margin_pct,
       ROUND(COALESCE(i.invoiced, 0) * 100.0 / NULLIF(t.standard_value, 0), 1) AS realization_pct
FROM dim_project dp
JOIN dim_client dc ON dc.client_key = dp.client_key
JOIN t ON t.project_key = dp.project_key
LEFT JOIN i ON i.project_key = dp.project_key
LEFT JOIN p ON p.project_key = dp.project_key;

-- 3) Accounts receivable ageing at the reporting date, one row per open invoice
CREATE VIEW vw_ar_ageing AS
WITH paid AS (
  SELECT pay.invoice_key, SUM(pay.amount) AS paid_amount
  FROM fact_payment pay
  JOIN dim_date d ON d.date_key = pay.paid_date_key
  WHERE d.date <= (SELECT as_of_date FROM etl_config)
  GROUP BY pay.invoice_key
),
base AS (
  SELECT i.invoice_id, dc.client_name, dc.industry, dp.project_id,
         di.date AS invoice_date, dd.date AS due_date, i.amount,
         COALESCE(p.paid_amount, 0) AS paid_amount,
         i.amount - COALESCE(p.paid_amount, 0) AS outstanding,
         CAST(julianday((SELECT as_of_date FROM etl_config)) - julianday(dd.date) AS INTEGER) AS days_past_due
  FROM fact_invoice i
  JOIN dim_client dc  ON dc.client_key = i.client_key
  JOIN dim_project dp ON dp.project_key = i.project_key
  JOIN dim_date di    ON di.date_key = i.invoice_date_key
  JOIN dim_date dd    ON dd.date_key = i.due_date_key
  LEFT JOIN paid p    ON p.invoice_key = i.invoice_key
)
SELECT *,
       CASE WHEN days_past_due <= 0  THEN '0 Current'
            WHEN days_past_due <= 30 THEN '1 1-30 days'
            WHEN days_past_due <= 60 THEN '2 31-60 days'
            WHEN days_past_due <= 90 THEN '3 61-90 days'
            ELSE '4 90+ days' END AS ageing_bucket
FROM base
WHERE outstanding > 0.5;

-- 4) Client scorecard: billing, collection and how fast each client really pays
CREATE VIEW vw_client_scorecard AS
WITH settled AS (        -- invoices that are fully paid, with the date of the last receipt
  SELECT i.invoice_key, i.client_key, i.invoice_date_key, i.due_date_key, i.amount,
         SUM(pay.amount) AS paid, MAX(pay.paid_date_key) AS last_paid_date_key
  FROM fact_invoice i JOIN fact_payment pay ON pay.invoice_key = i.invoice_key
  GROUP BY i.invoice_key
  HAVING SUM(pay.amount) >= i.amount - 0.5
),
speed AS (
  SELECT s.client_key,
         ROUND(AVG(julianday(dl.date) - julianday(di.date)), 1) AS avg_days_to_pay,
         ROUND(AVG(julianday(dl.date) - julianday(dd.date)), 1) AS avg_days_late
  FROM settled s
  JOIN dim_date di ON di.date_key = s.invoice_date_key
  JOIN dim_date dd ON dd.date_key = s.due_date_key
  JOIN dim_date dl ON dl.date_key = s.last_paid_date_key
  GROUP BY s.client_key
),
billed AS (SELECT client_key, SUM(amount) AS invoiced, COUNT(*) AS invoices FROM fact_invoice GROUP BY client_key),
cash AS (SELECT client_key, SUM(amount) AS collected FROM fact_payment GROUP BY client_key),
od AS (SELECT client_name, SUM(outstanding) AS outstanding,
              SUM(CASE WHEN days_past_due > 0 THEN outstanding ELSE 0 END) AS overdue
       FROM vw_ar_ageing GROUP BY client_name)
SELECT dc.client_id, dc.client_name, dc.industry, dc.tier, dc.payment_terms_days,
       b.invoices, ROUND(b.invoiced) AS invoiced, ROUND(COALESCE(c.collected, 0)) AS collected,
       ROUND(COALESCE(od.outstanding, 0)) AS outstanding, ROUND(COALESCE(od.overdue, 0)) AS overdue,
       s.avg_days_to_pay, s.avg_days_late
FROM dim_client dc
JOIN billed b ON b.client_key = dc.client_key
LEFT JOIN cash c ON c.client_key = dc.client_key
LEFT JOIN od ON od.client_name = dc.client_name
LEFT JOIN speed s ON s.client_key = dc.client_key;

-- 5) Unbilled work in progress: billable work in months that have no invoice yet, valued at standard rates
CREATE VIEW vw_wip_unbilled AS
WITH work AS (
  SELECT f.project_key, substr(d.date, 1, 7) AS period, SUM(f.standard_value) AS value, SUM(f.billable_hours) AS hours
  FROM fact_timesheet f JOIN dim_date d ON d.date_key = f.date_key
  WHERE f.is_billable = 1
  GROUP BY f.project_key, substr(d.date, 1, 7)
)
SELECT dp.project_id, dp.project_name, dc.client_name, dp.practice, w.period,
       ROUND(w.hours, 1) AS billable_hours, ROUND(w.value) AS wip_value
FROM work w
JOIN dim_project dp ON dp.project_key = w.project_key
JOIN dim_client dc  ON dc.client_key = dp.client_key
WHERE NOT EXISTS (SELECT 1 FROM fact_invoice i
                  WHERE i.project_key = w.project_key AND i.billing_period = w.period);

-- 6) Monthly financial summary for trend pages
CREATE VIEW vw_monthly_financials AS
WITH inv AS (
  SELECT d.year, d.month, SUM(i.amount) AS invoiced
  FROM fact_invoice i JOIN dim_date d ON d.date_key = i.invoice_date_key GROUP BY d.year, d.month
),
cash AS (
  SELECT d.year, d.month, SUM(p.amount) AS collected
  FROM fact_payment p JOIN dim_date d ON d.date_key = p.paid_date_key GROUP BY d.year, d.month
),
cost AS (
  SELECT d.year, d.month, SUM(f.cost_value) AS cost_value, SUM(f.billable_hours) AS billable_hours, SUM(f.hours) AS hours
  FROM fact_timesheet f JOIN dim_date d ON d.date_key = f.date_key GROUP BY d.year, d.month
)
SELECT c.year, c.month, ROUND(COALESCE(inv.invoiced, 0)) AS invoiced, ROUND(COALESCE(cash.collected, 0)) AS collected,
       ROUND(c.cost_value) AS cost_value, ROUND(c.hours, 1) AS hours, ROUND(c.billable_hours, 1) AS billable_hours
FROM cost c
LEFT JOIN inv  ON inv.year = c.year AND inv.month = c.month
LEFT JOIN cash ON cash.year = c.year AND cash.month = c.month
ORDER BY c.year, c.month;
