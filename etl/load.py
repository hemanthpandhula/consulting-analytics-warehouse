"""Load cleaned data into the SQLite star schema, then create the reporting views."""
import calendar
import datetime as dt
import sqlite3
from pathlib import Path

from .config import AS_OF, OPEN_END, WINDOW_START
from .transform import find_version, version_lookup

MONTH_NAMES = list(calendar.month_name)


def date_key(d: dt.date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def build_dim_date(start=WINDOW_START, end=dt.date(2026, 12, 31)):
    rows, d = [], start
    while d <= end:
        fy = d.year + 1 if d.month >= 4 else d.year
        fq = ((d.month - 4) % 12) // 3 + 1
        rows.append((date_key(d), d.isoformat(), d.year, d.month, MONTH_NAMES[d.month], (d.month - 1) // 3 + 1,
                     1 if d.weekday() >= 5 else 0, f"FY{str(fy)[2:]}", f"Q{fq}"))
        d += dt.timedelta(days=1)
    return rows


def load(paths, clients, projects, versions, timesheets, invoices, payments, dq):
    paths.out.mkdir(parents=True, exist_ok=True)
    if paths.db.exists():
        paths.db.unlink()
    con = sqlite3.connect(paths.db)
    con.executescript((paths.sql / "01_schema.sql").read_text())
    cur = con.cursor()
    cur.execute("INSERT INTO etl_config VALUES (?)", (AS_OF.isoformat(),))
    cur.executemany("INSERT INTO dim_date VALUES (?,?,?,?,?,?,?,?,?)", build_dim_date())

    client_key = {}
    for i, c in enumerate(sorted(clients, key=lambda x: x["client_id"]), 1):
        client_key[c["client_id"]] = i
        cur.execute("INSERT INTO dim_client VALUES (?,?,?,?,?,?,?)",
                    (i, c["client_id"], c["client_name"], c["industry"], c["city"], c["payment_terms_days"], c["tier"]))

    project_key, project_client = {}, {}
    for i, p in enumerate(sorted(projects, key=lambda x: x["project_id"]), 1):
        project_key[p["project_id"]] = i
        project_client[p["project_id"]] = client_key[p["client_id"]]
        cur.execute("INSERT INTO dim_project VALUES (?,?,?,?,?,?,?,?,?)",
                    (i, p["project_id"], client_key[p["client_id"]], p["project_name"], p["practice"], p["billing_type"],
                     p["start_date"].isoformat(), p["end_date"].isoformat(), p["budget_hours"]))

    ekey = {}
    for i, v in enumerate(sorted(versions, key=lambda x: (x["employee_id"], x["valid_from"])), 1):
        ekey[(v["employee_id"], v["valid_from"])] = i
        cur.execute("INSERT INTO dim_employee VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (i, v["employee_id"], v["full_name"], v["practice"], v["location"], v["grade"], v["bill_rate"],
                     v["cost_rate"], v["valid_from"].isoformat(), v["valid_to"].isoformat(), int(v["is_current"])))

    lookup = version_lookup(versions)
    rows = []
    for n, t in enumerate(sorted(timesheets, key=lambda x: x["timesheet_id"]), 1):
        v = find_version(lookup, t["employee_id"], t["work_date"])
        bh = t["hours"] if t["is_billable"] else 0.0
        rows.append((n, t["timesheet_id"], date_key(t["work_date"]), ekey[(v["employee_id"], v["valid_from"])],
                     project_key[t["project_id"]], project_client[t["project_id"]], t["hours"], int(t["is_billable"]),
                     bh, bh * v["bill_rate"], t["hours"] * v["cost_rate"]))
    cur.executemany("INSERT INTO fact_timesheet VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)

    inv_key = {}
    for n, inv in enumerate(sorted(invoices, key=lambda x: x["invoice_id"]), 1):
        inv_key[inv["invoice_id"]] = (n, client_key[inv["client_id"]])
        cur.execute("INSERT INTO fact_invoice VALUES (?,?,?,?,?,?,?,?)",
                    (n, inv["invoice_id"], date_key(inv["invoice_date"]), date_key(inv["due_date"]),
                     client_key[inv["client_id"]], project_key[inv["project_id"]], inv["billing_period"], inv["amount"]))
    for n, p in enumerate(sorted(payments, key=lambda x: x["payment_id"]), 1):
        k, ck = inv_key[p["invoice_id"]]
        cur.execute("INSERT INTO fact_payment VALUES (?,?,?,?,?,?,?)",
                    (n, p["payment_id"], k, date_key(p["paid_date"]), ck, p["amount"], p["method"]))

    cur.executemany("INSERT INTO dq_quarantine VALUES (?,?,?)", [(a, b, c) for a, b, c in dq.quarantine])
    con.executescript((paths.sql / "02_views.sql").read_text())
    con.commit()
    return con
