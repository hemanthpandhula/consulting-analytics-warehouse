-- MySQL 8 stored procedures and a function for the same warehouse.
-- Status: written for MySQL 8.0+ (Community edition is free). The logic mirrors the SQLite views that
-- tests/test_pipeline.py exercises, but these MySQL objects have NOT been executed in this repository's test run.
-- Import the CSVs from output/marts (MySQL Workbench Table Data Import Wizard), then run this script.

DELIMITER //

CREATE FUNCTION fn_utilization_pct (p_billable DECIMAL(12,2), p_capacity DECIMAL(12,2))
RETURNS DECIMAL(6,1)
DETERMINISTIC
BEGIN
    RETURN ROUND(100.0 * p_billable / NULLIF(p_capacity, 0), 1);
END //

-- Open invoices and their ageing bucket on any reporting date:  CALL sp_ar_ageing('2026-10-31');
CREATE PROCEDURE sp_ar_ageing (IN p_as_of DATE)
BEGIN
    WITH paid AS (
        SELECT p.invoice_key, SUM(p.amount) AS paid_amount
        FROM fact_payment p
        JOIN dim_date d ON d.date_key = p.paid_date_key
        WHERE d.`date` <= p_as_of
        GROUP BY p.invoice_key
    ),
    base AS (
        SELECT dc.client_name, i.invoice_id, dd.`date` AS due_date,
               i.amount - COALESCE(p.paid_amount, 0) AS outstanding,
               DATEDIFF(p_as_of, dd.`date`)          AS days_past_due
        FROM fact_invoice i
        JOIN dim_client dc ON dc.client_key = i.client_key
        JOIN dim_date  dd ON dd.date_key   = i.due_date_key
        LEFT JOIN paid p   ON p.invoice_key = i.invoice_key
    )
    SELECT client_name, invoice_id, due_date, outstanding, days_past_due,
           CASE WHEN days_past_due <= 0  THEN '0 Current'
                WHEN days_past_due <= 30 THEN '1 1-30 days'
                WHEN days_past_due <= 60 THEN '2 31-60 days'
                WHEN days_past_due <= 90 THEN '3 61-90 days'
                ELSE '4 90+ days' END AS ageing_bucket
    FROM base
    WHERE outstanding > 0.5
    ORDER BY days_past_due DESC, outstanding DESC;
END //

-- Project margin, optionally for one practice:  CALL sp_project_margin('Risk Advisory');  or  CALL sp_project_margin(NULL);
CREATE PROCEDURE sp_project_margin (IN p_practice VARCHAR(60))
BEGIN
    WITH t AS (
        SELECT project_key, SUM(hours) AS hours, SUM(standard_value) AS standard_value, SUM(cost_value) AS cost_value
        FROM fact_timesheet GROUP BY project_key
    ),
    i AS (
        SELECT project_key, SUM(amount) AS invoiced FROM fact_invoice GROUP BY project_key
    )
    SELECT dp.project_id, dp.project_name, dp.practice,
           ROUND(t.hours, 1)                                              AS hours,
           ROUND(100.0 * t.hours / NULLIF(dp.budget_hours, 0), 1)         AS budget_burn_pct,
           COALESCE(i.invoiced, 0)                                        AS invoiced,
           t.cost_value,
           COALESCE(i.invoiced, 0) - t.cost_value                         AS margin,
           ROUND(100.0 * (COALESCE(i.invoiced, 0) - t.cost_value) / NULLIF(i.invoiced, 0), 1) AS margin_pct,
           ROUND(100.0 * COALESCE(i.invoiced, 0) / NULLIF(t.standard_value, 0), 1)           AS realization_pct
    FROM dim_project dp
    JOIN t ON t.project_key = dp.project_key
    LEFT JOIN i ON i.project_key = dp.project_key
    WHERE p_practice IS NULL OR dp.practice = p_practice
    ORDER BY margin_pct ASC;
END //

DELIMITER ;
