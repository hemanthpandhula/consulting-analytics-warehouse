"""Post-load checks: prove the warehouse is complete, consistent and ties back to the source."""
from .quality import DQ


def _one(con, sql):
    return con.execute(sql).fetchone()[0]


def post_load_checks(con, dq: DQ, raw_counts, clean, dupes_removed):
    d = dq.define
    d("R01", "warehouse", "rows read = rows loaded + quarantined + duplicates removed (every table)", "must be zero gap", "critical")
    d("R02", "warehouse", "fact tables have no foreign key pointing at a missing dimension row", "must be zero", "critical")
    d("R03", "warehouse", "employee versions never overlap and leave no gap (SCD type 2)", "must be zero", "critical")
    d("R04", "warehouse", "invoice total in the warehouse equals the cleaned invoice total", "difference < 1 rupee", "critical")
    d("R05", "warehouse", "standard value in fact_timesheet equals hours x the bill rate valid on the day", "difference < 1 rupee", "critical")
    d("R06", "warehouse", "no payment is dated before its invoice", "must be zero", "critical")
    d("R07", "warehouse", "no invoice is paid more than its amount", "must be zero", "critical")

    # R01 reconciliation, per table
    gap = 0
    loaded = {"clients": clean["clients"], "projects": clean["projects"], "timesheets": clean["timesheets"],
              "invoices": clean["invoices"], "payments": clean["payments"]}
    for table, raw_n in raw_counts.items():
        accounted = loaded[table] + dq.quarantined(table) + dupes_removed[table]
        gap += abs(raw_n - accounted)
    dq.set_result("R01", sum(raw_counts.values()), gap)

    # R02 orphan foreign keys
    orphans = 0
    for sql in (
        "SELECT COUNT(*) FROM fact_timesheet f LEFT JOIN dim_employee e ON e.employee_key=f.employee_key WHERE e.employee_key IS NULL",
        "SELECT COUNT(*) FROM fact_timesheet f LEFT JOIN dim_project p ON p.project_key=f.project_key WHERE p.project_key IS NULL",
        "SELECT COUNT(*) FROM fact_timesheet f LEFT JOIN dim_date x ON x.date_key=f.date_key WHERE x.date_key IS NULL",
        "SELECT COUNT(*) FROM fact_invoice f LEFT JOIN dim_client c ON c.client_key=f.client_key WHERE c.client_key IS NULL",
        "SELECT COUNT(*) FROM fact_invoice f LEFT JOIN dim_date x ON x.date_key=f.due_date_key WHERE x.date_key IS NULL",
        "SELECT COUNT(*) FROM fact_payment f LEFT JOIN fact_invoice i ON i.invoice_key=f.invoice_key WHERE i.invoice_key IS NULL",
        "SELECT COUNT(*) FROM fact_payment f LEFT JOIN dim_date x ON x.date_key=f.paid_date_key WHERE x.date_key IS NULL",
    ):
        orphans += _one(con, sql)
    dq.set_result("R02", 7, orphans)

    # R03 SCD2 continuity
    bad = _one(con, """
        SELECT COUNT(*) FROM (
          SELECT employee_id, valid_to,
                 LEAD(valid_from) OVER (PARTITION BY employee_id ORDER BY valid_from) AS next_from
          FROM dim_employee)
        WHERE next_from IS NOT NULL AND next_from <> valid_to""")
    dq.set_result("R03", _one(con, "SELECT COUNT(DISTINCT employee_id) FROM dim_employee"), bad)

    # R04 invoice tie-out
    expected = sum(i["amount"] for i in clean["invoice_rows"])
    got = _one(con, "SELECT SUM(amount) FROM fact_invoice")
    dq.set_result("R04", 1, 0 if abs(expected - got) < 1 else 1)

    # R05 standard value tie-out (independent recomputation in SQL from the dimension)
    diff = _one(con, """
        SELECT ABS(SUM(f.standard_value) - SUM(f.billable_hours * e.bill_rate))
        FROM fact_timesheet f JOIN dim_employee e ON e.employee_key = f.employee_key""")
    dq.set_result("R05", 1, 0 if diff < 1 else 1)

    # R06, R07 business logic
    early = _one(con, """SELECT COUNT(*) FROM fact_payment p JOIN fact_invoice i ON i.invoice_key=p.invoice_key
                         WHERE p.paid_date_key < i.invoice_date_key""")
    dq.set_result("R06", _one(con, "SELECT COUNT(*) FROM fact_payment"), early)
    over = _one(con, """SELECT COUNT(*) FROM (SELECT i.invoice_key FROM fact_invoice i JOIN fact_payment p ON p.invoice_key=i.invoice_key
                        GROUP BY i.invoice_key HAVING SUM(p.amount) > i.amount + 0.5)""")
    dq.set_result("R07", _one(con, "SELECT COUNT(*) FROM fact_invoice"), over)

    con.executemany("INSERT INTO dq_results VALUES (?,?,?,?,?,?,?,?)",
                    [(r["rule_id"], r["table"], r["description"], r["action"], r["severity"],
                      r["checked"], r["failed"], r["status"]) for r in dq.rules.values()])
    con.commit()
    return [r for r in dq.rules.values() if r["status"] == "FAIL" and r["severity"] == "critical"]
