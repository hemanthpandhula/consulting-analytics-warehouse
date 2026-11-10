"""Orchestrator: extract -> clean -> load -> verify -> publish marts and reports."""
import csv
import json
import time
from pathlib import Path

from . import generate_source, transform as T
from .checks import post_load_checks
from .config import AS_OF, Paths, default_paths
from .load import load
from .quality import DQ
from .report import write_reports

MART_TABLES = ["dim_date", "dim_client", "dim_project", "dim_employee", "fact_timesheet", "fact_invoice", "fact_payment"]
MART_VIEWS = ["vw_utilization_monthly", "vw_project_profitability", "vw_ar_ageing", "vw_client_scorecard",
              "vw_wip_unbilled", "vw_monthly_financials"]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def export_marts(con, paths: Paths):
    paths.marts.mkdir(parents=True, exist_ok=True)
    for name in MART_TABLES + MART_VIEWS:
        cur = con.execute(f"SELECT * FROM {name}")
        with open(paths.marts / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([c[0] for c in cur.description])
            w.writerows(cur)


def run(paths: Paths = None, regenerate: bool = True) -> dict:
    paths = paths or default_paths()
    started = time.time()
    if regenerate or not (paths.raw / "timesheets.csv").exists():
        log("Generating synthetic source extracts")
        generate_source.generate(paths.raw)

    log("Extract: reading raw CSV files")
    raw = {n: T.read_csv(paths.raw / f"{n}.csv") for n in
           ("clients", "projects", "employees", "employee_grade_history", "rate_card", "timesheets", "invoices", "payments")}
    raw_counts = {k: len(raw[k]) for k in ("clients", "projects", "timesheets", "invoices", "payments")}

    log("Transform: cleaning, standardising, validating")
    dq = DQ()
    T.define_rules(dq)
    clients = T.clean_clients(raw["clients"], dq)
    client_ids = {c["client_id"] for c in clients}
    projects = T.clean_projects(raw["projects"], client_ids, dq)
    project_ids = {p["project_id"] for p in projects}
    project_client = {p["project_id"]: p["client_id"] for p in projects}
    versions = T.build_employee_versions(raw["employees"], raw["employee_grade_history"], raw["rate_card"], dq)
    lookup = T.version_lookup(versions)
    timesheets = T.clean_timesheets(raw["timesheets"], lookup, project_ids, dq)
    invoices = T.clean_invoices(raw["invoices"], project_client, dq)
    payments = T.clean_payments(raw["payments"], {i["invoice_id"]: i for i in invoices}, dq)

    log("Load: building the star schema and reporting views")
    con = load(paths, clients, projects, versions, timesheets, invoices, payments, dq)

    log("Verify: reconciliation and integrity checks")
    dupes = {"clients": dq.rules["C01"]["failed"], "projects": 0, "timesheets": dq.rules["T01"]["failed"],
             "invoices": dq.rules["I01"]["failed"], "payments": dq.rules["Y01"]["failed"]}
    clean = {"clients": len(clients), "projects": len(projects), "timesheets": len(timesheets),
             "invoices": len(invoices), "payments": len(payments), "invoice_rows": invoices}
    failures = post_load_checks(con, dq, raw_counts, clean, dupes)

    log("Publish: exporting marts for Power BI / Tableau and writing reports")
    export_marts(con, paths)
    summary = {"as_of": AS_OF.isoformat(), "raw_rows": raw_counts,
               "loaded_rows": {k: v for k, v in clean.items() if k != "invoice_rows"},
               "duplicates_removed": dupes,
               "quarantined": {t: dq.quarantined(t) for t in raw_counts},
               "critical_failures": [f["rule_id"] for f in failures],
               "seconds": round(time.time() - started, 1)}
    write_reports(con, paths, dq, summary)
    (paths.out / "run_summary.json").write_text(json.dumps(summary, indent=2))
    con.close()
    log(f"Done in {summary['seconds']}s. Critical failures: {summary['critical_failures'] or 'none'}")
    return summary
