-- SQL Server (T-SQL) stored procedures and a function for the same warehouse.
-- Status: written for SQL Server 2019+ (Express edition is free). The logic mirrors the SQLite views that
-- tests/test_pipeline.py exercises, but these T-SQL objects have NOT been executed in this repository's test run.
-- Load the CSVs from output/marts into tables named like the files (SSMS Import Flat File wizard), then run this script.
-- Remember to convert the *_key and date columns to INT and DATE during import.

CREATE OR ALTER FUNCTION dbo.fn_utilization_pct (@billable DECIMAL(12,2), @capacity DECIMAL(12,2))
RETURNS DECIMAL(6,1)
AS
BEGIN
    RETURN CAST(100.0 * @billable / NULLIF(@capacity, 0) AS DECIMAL(6,1));
END;
GO

-- Open invoices and their ageing bucket on any reporting date
CREATE OR ALTER PROCEDURE dbo.sp_ar_ageing
    @as_of DATE
AS
BEGIN
    SET NOCOUNT ON;

    WITH paid AS (
        SELECT p.invoice_key, SUM(p.amount) AS paid_amount
        FROM dbo.fact_payment p
        JOIN dbo.dim_date d ON d.date_key = p.paid_date_key
        WHERE d.[date] <= @as_of
        GROUP BY p.invoice_key
    ),
    base AS (
        SELECT dc.client_name, i.invoice_id, dd.[date] AS due_date,
               i.amount - COALESCE(p.paid_amount, 0) AS outstanding,
               DATEDIFF(DAY, dd.[date], @as_of)      AS days_past_due
        FROM dbo.fact_invoice i
        JOIN dbo.dim_client dc ON dc.client_key = i.client_key
        JOIN dbo.dim_date  dd ON dd.date_key   = i.due_date_key
        LEFT JOIN paid p       ON p.invoice_key = i.invoice_key
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
END;
GO

-- Project margin, optionally for one practice. EXEC dbo.sp_project_margin @practice = N'Risk Advisory';
CREATE OR ALTER PROCEDURE dbo.sp_project_margin
    @practice NVARCHAR(60) = NULL
AS
BEGIN
    SET NOCOUNT ON;

    WITH t AS (
        SELECT project_key, SUM(hours) AS hours, SUM(standard_value) AS standard_value, SUM(cost_value) AS cost_value
        FROM dbo.fact_timesheet GROUP BY project_key
    ),
    i AS (
        SELECT project_key, SUM(amount) AS invoiced FROM dbo.fact_invoice GROUP BY project_key
    )
    SELECT dp.project_id, dp.project_name, dp.practice,
           CAST(t.hours AS DECIMAL(12,1))                                         AS hours,
           CAST(100.0 * t.hours / NULLIF(dp.budget_hours, 0) AS DECIMAL(6,1))     AS budget_burn_pct,
           COALESCE(i.invoiced, 0)                                                AS invoiced,
           t.cost_value,
           COALESCE(i.invoiced, 0) - t.cost_value                                 AS margin,
           CAST(100.0 * (COALESCE(i.invoiced, 0) - t.cost_value) / NULLIF(i.invoiced, 0) AS DECIMAL(6,1)) AS margin_pct,
           CAST(100.0 * COALESCE(i.invoiced, 0) / NULLIF(t.standard_value, 0) AS DECIMAL(6,1))           AS realization_pct
    FROM dbo.dim_project dp
    JOIN t ON t.project_key = dp.project_key
    LEFT JOIN i ON i.project_key = dp.project_key
    WHERE (@practice IS NULL OR dp.practice = @practice)
    ORDER BY margin_pct ASC;
END;
GO
