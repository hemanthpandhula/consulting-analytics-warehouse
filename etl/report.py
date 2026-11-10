"""Human-readable outputs: a data-quality report and a short business summary computed from the views."""


def _fmt_inr(v):
    v = float(v or 0)
    return f"₹{v / 1e7:.2f} Cr" if abs(v) >= 1e7 else f"₹{v / 1e5:.1f} L"


def write_reports(con, paths, dq, summary):
    # ---------- data quality report ----------
    lines = ["# Data quality report", "", f"Reporting date: {summary['as_of']}", "",
             "## Reconciliation", "", "| Table | Rows read | Duplicates removed | Quarantined | Loaded |", "|---|---:|---:|---:|---:|"]
    for t, n in summary["raw_rows"].items():
        lines.append(f"| {t} | {n:,} | {summary['duplicates_removed'][t]:,} | {summary['quarantined'][t]:,} | {summary['loaded_rows'][t]:,} |")
    lines += ["", "## Rules", "", "| Rule | Table | What it checks | Rows checked | Rows failed | Action | Severity | Status |",
              "|---|---|---|---:|---:|---|---|---|"]
    for r in dq.rules.values():
        lines.append(f"| {r['rule_id']} | {r['table']} | {r['description']} | {r['checked']:,} | {r['failed']:,} | {r['action']} | {r['severity']} | {r['status']} |")
    lines += ["", "Rows that fail a *quarantine* rule are not loaded. They are kept in the `dq_quarantine` table with the rule id and the full source row, so a data owner can correct them at source.", ""]
    (paths.out / "dq_report.md").write_text("\n".join(lines), encoding="utf-8")

    # ---------- business summary ----------
    q = lambda sql: con.execute(sql).fetchall()
    one = lambda sql: con.execute(sql).fetchone()[0]
    out = ["# Business summary (from the warehouse views)", "", f"Reporting date: {summary['as_of']}. All data is synthetic.", ""]

    util = one("SELECT ROUND(SUM(billable_hours)*100.0/SUM(capacity_hours),1) FROM vw_utilization_monthly WHERE year=2026")
    out += [f"- Utilization in 2026 (billable hours / available hours): **{util}%**"]
    for p, u in q("SELECT practice, ROUND(SUM(billable_hours)*100.0/SUM(capacity_hours),1) u FROM vw_utilization_monthly WHERE year=2026 GROUP BY practice ORDER BY u DESC"):
        out.append(f"  - {p}: {u}%")

    inv, cost = one("SELECT SUM(invoiced) FROM vw_project_profitability"), one("SELECT SUM(cost_value) FROM vw_project_profitability")
    real = one("SELECT ROUND(SUM(invoiced)*100.0/SUM(standard_value),1) FROM vw_project_profitability")
    out += ["", f"- Invoiced {_fmt_inr(inv)} against delivery cost {_fmt_inr(cost)}: margin **{(inv - cost) * 100 / inv:.1f}%**; realization of standard value **{real}%**"]
    out.append("- Margin by practice:")
    for p, m in q("SELECT practice, ROUND((SUM(invoiced)-SUM(cost_value))*100.0/SUM(invoiced),1) m FROM vw_project_profitability GROUP BY practice ORDER BY m DESC"):
        out.append(f"  - {p}: {m}%")
    over = one("SELECT COUNT(*) FROM vw_project_profitability WHERE budget_burn_pct > 100")
    out.append(f"- Projects over their hours budget: **{over}** of {one('SELECT COUNT(*) FROM vw_project_profitability')}")

    outstanding = one("SELECT SUM(outstanding) FROM vw_ar_ageing")
    overdue = one("SELECT SUM(outstanding) FROM vw_ar_ageing WHERE days_past_due>0")
    o90 = one("SELECT SUM(outstanding) FROM vw_ar_ageing WHERE days_past_due>90")
    out += ["", f"- Receivables outstanding {_fmt_inr(outstanding)}; overdue {_fmt_inr(overdue)} ({overdue * 100 / outstanding:.0f}%); over 90 days {_fmt_inr(o90)}"]
    out.append("- Slowest-paying clients (average days late on settled invoices):")
    for n, d, od in q("SELECT client_name, avg_days_late, overdue FROM vw_client_scorecard WHERE avg_days_late IS NOT NULL ORDER BY avg_days_late DESC LIMIT 3"):
        out.append(f"  - {n}: {d} days late on average, {_fmt_inr(od)} overdue now")
    wip = one("SELECT SUM(wip_value) FROM vw_wip_unbilled")
    out += ["", f"- Unbilled work in progress at standard rates: **{_fmt_inr(wip)}**"]

    promo = one("SELECT COUNT(*) FROM dim_employee WHERE is_current=0")
    out += ["", f"- Grade changes tracked with SCD type 2: **{promo}** historical employee versions, so past hours keep the rate that applied on the day"]
    (paths.out / "business_summary.md").write_text("\n".join(out) + "\n", encoding="utf-8")
