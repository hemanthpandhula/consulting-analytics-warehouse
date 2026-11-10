-- Analysis queries a practice leader would ask for. Window functions, CTEs and the SCD2 dimension in use.
-- Run any of them against output/warehouse.db (tests/test_pipeline.py executes every one).

-- Q1. Which five clients bring the most delivery margin, and how do they rank on realization?
SELECT dc.client_name,
       ROUND(SUM(v.invoiced))                                              AS invoiced,
       ROUND(SUM(v.invoiced) - SUM(v.cost_value))                          AS margin,
       ROUND(100.0 * (SUM(v.invoiced) - SUM(v.cost_value)) / SUM(v.invoiced), 1) AS margin_pct,
       ROUND(100.0 * SUM(v.invoiced) / SUM(v.standard_value), 1)           AS realization_pct,
       RANK() OVER (ORDER BY SUM(v.invoiced) - SUM(v.cost_value) DESC)     AS margin_rank
FROM vw_project_profitability v
JOIN dim_client dc ON dc.client_name = v.client_name
GROUP BY dc.client_name
ORDER BY margin_rank
LIMIT 5;

-- Q2. Month-on-month invoicing growth with a three-month moving average
SELECT year, month, invoiced,
       ROUND(100.0 * (invoiced - LAG(invoiced) OVER (ORDER BY year, month))
             / LAG(invoiced) OVER (ORDER BY year, month), 1)               AS mom_growth_pct,
       ROUND(AVG(invoiced) OVER (ORDER BY year, month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)) AS moving_avg_3m
FROM vw_monthly_financials
ORDER BY year, month;

-- Q3. Projects that have used more hours than budgeted, worst first within each practice
SELECT practice, project_id, project_name, hours, budget_hours,
       ROUND(hours - budget_hours, 1)                                       AS overrun_hours,
       RANK() OVER (PARTITION BY practice ORDER BY hours - budget_hours DESC) AS rank_in_practice
FROM vw_project_profitability
WHERE hours > budget_hours
ORDER BY practice, rank_in_practice;

-- Q4. Bench risk: ten lowest-utilized people over the last three months
SELECT employee_id, full_name, practice,
       ROUND(SUM(billable_hours) * 100.0 / SUM(capacity_hours), 1) AS utilization_last_3m
FROM vw_utilization_monthly
WHERE month_start >= date((SELECT as_of_date FROM etl_config), 'start of month', '-2 months')
GROUP BY employee_id, full_name, practice
ORDER BY utilization_last_3m
LIMIT 10;

-- Q5. Promotion history: billable hours and value earned at each grade (uses the SCD type 2 versions)
SELECT e.employee_id, e.full_name, e.grade, e.valid_from, e.valid_to,
       ROUND(SUM(f.billable_hours), 1) AS billable_hours,
       ROUND(SUM(f.standard_value))    AS standard_value
FROM dim_employee e
JOIN fact_timesheet f ON f.employee_key = e.employee_key
WHERE e.employee_id IN (SELECT employee_id FROM dim_employee WHERE is_current = 0)
GROUP BY e.employee_key
ORDER BY e.employee_id, e.valid_from;

-- Q6. Cumulative billing against cumulative cash collected
SELECT year, month, invoiced, collected,
       SUM(invoiced)  OVER (ORDER BY year, month) AS cumulative_invoiced,
       SUM(collected) OVER (ORDER BY year, month) AS cumulative_collected,
       ROUND(100.0 * SUM(collected) OVER (ORDER BY year, month)
             / SUM(invoiced) OVER (ORDER BY year, month), 1) AS cumulative_collection_pct
FROM vw_monthly_financials
ORDER BY year, month;

-- Q7. Client concentration: share of billing and cumulative share (Pareto)
WITH c AS (SELECT client_name, invoiced FROM vw_client_scorecard),
     t AS (SELECT SUM(invoiced) AS total FROM c)
SELECT client_name, invoiced,
       ROUND(100.0 * invoiced / total, 1)                                  AS share_pct,
       ROUND(100.0 * SUM(invoiced) OVER (ORDER BY invoiced DESC) / total, 1) AS cumulative_share_pct
FROM c, t
ORDER BY invoiced DESC
LIMIT 10;

-- Q8. Receivables by ageing bucket
SELECT ageing_bucket, COUNT(*) AS invoices, ROUND(SUM(outstanding)) AS outstanding,
       ROUND(100.0 * SUM(outstanding) / SUM(SUM(outstanding)) OVER (), 1) AS share_pct
FROM vw_ar_ageing
GROUP BY ageing_bucket
ORDER BY ageing_bucket;

-- Q9. What did data quality cost? Rows quarantined by rule
SELECT q.rule_id, r.description, COUNT(*) AS rows_quarantined
FROM dq_quarantine q
JOIN dq_results r ON r.rule_id = q.rule_id
GROUP BY q.rule_id, r.description
ORDER BY rows_quarantined DESC;
