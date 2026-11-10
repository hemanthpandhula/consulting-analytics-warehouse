-- Star schema for consulting-practice reporting. Tested on SQLite; types map directly to SQL Server / MySQL.
-- Conformed dimensions: dim_date, dim_client, dim_project, dim_employee (SCD type 2).
-- Facts: fact_timesheet (grain: one timesheet line), fact_invoice (one invoice), fact_payment (one receipt).

PRAGMA foreign_keys = ON;

CREATE TABLE etl_config (
  as_of_date TEXT NOT NULL            -- reporting date used by the ageing, WIP and utilization views
);

CREATE TABLE dim_date (
  date_key        INTEGER PRIMARY KEY,   -- yyyymmdd
  date            TEXT    NOT NULL UNIQUE,
  year            INTEGER NOT NULL,
  month           INTEGER NOT NULL,
  month_name      TEXT    NOT NULL,
  quarter         INTEGER NOT NULL,
  is_weekend      INTEGER NOT NULL,
  fiscal_year     TEXT    NOT NULL,      -- Indian financial year, April to March, e.g. FY26
  fiscal_quarter  TEXT    NOT NULL       -- Q1 = Apr-Jun
);

CREATE TABLE dim_client (
  client_key          INTEGER PRIMARY KEY,
  client_id           TEXT NOT NULL UNIQUE,
  client_name         TEXT NOT NULL,
  industry            TEXT NOT NULL,
  city                TEXT NOT NULL,
  payment_terms_days  INTEGER NOT NULL,
  tier                TEXT NOT NULL
);

CREATE TABLE dim_project (
  project_key    INTEGER PRIMARY KEY,
  project_id     TEXT NOT NULL UNIQUE,
  client_key     INTEGER NOT NULL REFERENCES dim_client (client_key),
  project_name   TEXT NOT NULL,
  practice       TEXT NOT NULL,
  billing_type   TEXT NOT NULL,
  start_date     TEXT NOT NULL,
  end_date       TEXT NOT NULL,
  budget_hours   REAL NOT NULL
);

CREATE TABLE dim_employee (               -- SCD type 2: a new row is written when an employee's grade changes
  employee_key  INTEGER PRIMARY KEY,
  employee_id   TEXT NOT NULL,
  full_name     TEXT NOT NULL,
  practice      TEXT NOT NULL,
  location      TEXT NOT NULL,
  grade         TEXT NOT NULL,
  bill_rate     REAL NOT NULL,
  cost_rate     REAL NOT NULL,
  valid_from    TEXT NOT NULL,
  valid_to      TEXT NOT NULL,            -- exclusive; 9999-12-31 for the current version
  is_current    INTEGER NOT NULL,
  UNIQUE (employee_id, valid_from)
);

CREATE TABLE fact_timesheet (
  timesheet_key   INTEGER PRIMARY KEY,
  timesheet_id    TEXT NOT NULL UNIQUE,
  date_key        INTEGER NOT NULL REFERENCES dim_date (date_key),
  employee_key    INTEGER NOT NULL REFERENCES dim_employee (employee_key),   -- the version valid on work_date
  project_key     INTEGER NOT NULL REFERENCES dim_project (project_key),
  client_key      INTEGER NOT NULL REFERENCES dim_client (client_key),
  hours           REAL NOT NULL,
  is_billable     INTEGER NOT NULL,
  billable_hours  REAL NOT NULL,
  standard_value  REAL NOT NULL,          -- billable hours x bill rate valid on the day
  cost_value      REAL NOT NULL           -- hours x cost rate valid on the day
);

CREATE TABLE fact_invoice (
  invoice_key      INTEGER PRIMARY KEY,
  invoice_id       TEXT NOT NULL UNIQUE,
  invoice_date_key INTEGER NOT NULL REFERENCES dim_date (date_key),
  due_date_key     INTEGER NOT NULL REFERENCES dim_date (date_key),
  client_key       INTEGER NOT NULL REFERENCES dim_client (client_key),
  project_key      INTEGER NOT NULL REFERENCES dim_project (project_key),
  billing_period   TEXT NOT NULL,         -- yyyy-mm of the work being billed
  amount           REAL NOT NULL
);

CREATE TABLE fact_payment (
  payment_key    INTEGER PRIMARY KEY,
  payment_id     TEXT NOT NULL UNIQUE,
  invoice_key    INTEGER NOT NULL REFERENCES fact_invoice (invoice_key),
  paid_date_key  INTEGER NOT NULL REFERENCES dim_date (date_key),
  client_key     INTEGER NOT NULL REFERENCES dim_client (client_key),
  amount         REAL NOT NULL,
  method         TEXT NOT NULL
);

CREATE TABLE dq_quarantine (
  source_table  TEXT NOT NULL,
  rule_id       TEXT NOT NULL,
  row_json      TEXT NOT NULL
);

CREATE TABLE dq_results (
  rule_id      TEXT PRIMARY KEY,
  source_table TEXT NOT NULL,
  description  TEXT NOT NULL,
  action       TEXT NOT NULL,
  severity     TEXT NOT NULL,
  rows_checked INTEGER NOT NULL,
  rows_failed  INTEGER NOT NULL,
  status       TEXT NOT NULL
);

CREATE INDEX ix_ts_date     ON fact_timesheet (date_key);
CREATE INDEX ix_ts_employee ON fact_timesheet (employee_key);
CREATE INDEX ix_ts_project  ON fact_timesheet (project_key);
CREATE INDEX ix_inv_client  ON fact_invoice (client_key);
CREATE INDEX ix_pay_invoice ON fact_payment (invoice_key);
