"""Clean and conform the raw extracts.

Principles
  * Fix what can be fixed safely (case, whitespace, date format, number format, code variants).
  * Remove exact duplicates, keep the first occurrence.
  * Never silently drop a bad row: it goes to the quarantine table with a rule id and the full row.
"""
import csv
import datetime as dt
from bisect import bisect_right
from pathlib import Path

from .config import AS_OF, MAX_DAILY_HOURS, OPEN_END
from .quality import DQ

TRUE_FLAGS = {"Y", "YES", "TRUE", "1"}
FALSE_FLAGS = {"N", "NO", "FALSE", "0"}


def read_csv(path: Path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_date(s):
    """ISO first, then the legacy dd/mm/yyyy export. Returns (date, was_iso) or (None, False)."""
    s = (s or "").strip()
    for fmt, iso in (("%Y-%m-%d", True), ("%d/%m/%Y", False)):
        try:
            return dt.datetime.strptime(s, fmt).date(), iso
        except ValueError:
            continue
    return None, False


def norm_id(s):
    return (s or "").strip().upper()


def define_rules(dq: DQ):
    d = dq.define
    d("C01", "clients", "client_id appears more than once", "keep first, drop the rest")
    d("C02", "clients", "industry blank", "set to 'Unknown'")
    d("C03", "clients", "industry written in mixed case", "standardise to Title Case")
    d("P01", "projects", "project dates not ISO (dd/mm/yyyy)", "parse and convert")
    d("P02", "projects", "project references an unknown client", "quarantine", "critical")
    d("P03", "projects", "end_date before start_date or unreadable date", "quarantine", "critical")
    d("E01", "employee_grade_history", "first grade record does not start on the hire date", "report only")
    d("T01", "timesheets", "timesheet_id appears more than once", "keep first, drop the rest")
    d("T02", "timesheets", "hours missing or not a number", "quarantine", "critical")
    d("T03", "timesheets", f"hours <= 0 or > {MAX_DAILY_HOURS}", "quarantine", "critical")
    d("T04", "timesheets", "employee_id not found in HR", "quarantine", "critical")
    d("T05", "timesheets", "project_id not found in projects", "quarantine", "critical")
    d("T06", "timesheets", "work_date unreadable or after the reporting date", "quarantine", "critical")
    d("T07", "timesheets", "work_date before the employee's hire date", "quarantine", "critical")
    d("T08", "timesheets", "ids with stray case or whitespace", "trim and upper-case")
    d("T09", "timesheets", "billable flag written in a non-standard way (y, Yes, TRUE, 1 ...)", "map to Y / N")
    d("T10", "timesheets", "work_date not ISO (dd/mm/yyyy)", "parse and convert")
    d("I01", "invoices", "invoice_id appears more than once", "keep first, drop the rest")
    d("I02", "invoices", "client_id blank", "back-fill from the project")
    d("I03", "invoices", "client_id differs from the project's client", "quarantine", "critical")
    d("I04", "invoices", "amount stored as text with commas", "strip commas and convert")
    d("I05", "invoices", "due_date before invoice_date or unreadable date", "quarantine", "critical")
    d("I06", "invoices", "amount <= 0 or not a number", "quarantine", "critical")
    d("I07", "invoices", "project_id not found in projects", "quarantine", "critical")
    d("Y01", "payments", "payment_id appears more than once", "keep first, drop the rest")
    d("Y02", "payments", "invoice_id not found in invoices", "quarantine", "critical")
    d("Y03", "payments", "amount <= 0 or not a number", "quarantine", "critical")
    d("Y04", "payments", "paid_date unreadable, before the invoice date or after the reporting date", "quarantine", "critical")


def clean_clients(raw, dq: DQ):
    seen, out = set(), []
    for r in raw:
        cid = norm_id(r["client_id"])
        dq.hit("C01", cid in seen)
        if cid in seen:
            continue
        seen.add(cid)
        ind = (r["industry"] or "").strip()
        dq.hit("C02", ind == "")
        dq.hit("C03", ind != "" and ind != ind.title())
        out.append({"client_id": cid, "client_name": r["client_name"].strip(), "industry": ind.title() if ind else "Unknown",
                    "city": r["city"].strip(), "payment_terms_days": int(r["payment_terms_days"]), "tier": r["tier"].strip()})
    return out


def clean_projects(raw, client_ids, dq: DQ):
    out = []
    for r in raw:
        s, si = parse_date(r["start_date"])
        e, ei = parse_date(r["end_date"])
        dq.hit("P01", not (si and ei))
        cid = norm_id(r["client_id"])
        bad_client = cid not in client_ids
        dq.hit("P02", bad_client)
        bad_dates = s is None or e is None or e < s
        dq.hit("P03", bad_dates)
        if bad_client:
            dq.reject("P02", "projects", r); continue
        if bad_dates:
            dq.reject("P03", "projects", r); continue
        out.append({"project_id": norm_id(r["project_id"]), "client_id": cid, "project_name": r["project_name"].strip(),
                    "practice": r["practice"].strip(), "billing_type": r["billing_type"].strip(),
                    "start_date": s, "end_date": e, "budget_hours": float(r["budget_hours"])})
    return out


def build_employee_versions(employees, history, rate_card, dq: DQ):
    """Slowly changing dimension type 2: one row per employee per grade, with a validity window."""
    rates = {r["grade"].strip(): (float(r["bill_rate"]), float(r["cost_rate"])) for r in rate_card}
    hist = {}
    for r in history:
        d, _ = parse_date(r["effective_date"])
        hist.setdefault(norm_id(r["employee_id"]), []).append((d, r["grade"].strip()))
    versions = []
    for e in employees:
        eid = norm_id(e["employee_id"])
        hire, _ = parse_date(e["hire_date"])
        rows = sorted(hist.get(eid, []))
        dq.hit("E01", not rows or rows[0][0] != hire)
        for i, (eff, grade) in enumerate(rows):
            valid_to = rows[i + 1][0] if i + 1 < len(rows) else OPEN_END
            versions.append({"employee_id": eid, "full_name": e["full_name"].strip(), "practice": e["practice"].strip(),
                             "location": e["location"].strip(), "grade": grade, "bill_rate": rates[grade][0],
                             "cost_rate": rates[grade][1], "valid_from": eff, "valid_to": valid_to,
                             "is_current": valid_to == OPEN_END})
    return versions


def version_lookup(versions):
    """employee_id -> sorted valid_from list and versions, for point-in-time joins."""
    by = {}
    for v in versions:
        by.setdefault(v["employee_id"], []).append(v)
    return {k: ([x["valid_from"] for x in sorted(v, key=lambda z: z["valid_from"])],
                sorted(v, key=lambda z: z["valid_from"])) for k, v in by.items()}


def find_version(lookup, eid, d):
    if eid not in lookup:
        return None
    starts, vs = lookup[eid]
    i = bisect_right(starts, d) - 1
    return vs[i] if i >= 0 else None


def clean_timesheets(raw, emp_lookup, project_ids, dq: DQ):
    seen, out = set(), []
    for r in raw:
        tid = r["timesheet_id"].strip()
        dup = tid in seen
        dq.hit("T01", dup)
        if dup:
            continue
        seen.add(tid)
        eid, pid = norm_id(r["employee_id"]), norm_id(r["project_id"])
        dq.hit("T08", eid != r["employee_id"] or pid != r["project_id"])
        d, iso = parse_date(r["work_date"])
        dq.hit("T10", d is not None and not iso)
        try:
            h = float(r["hours"])
            bad_h = False
        except ValueError:
            h, bad_h = None, True
        dq.hit("T02", bad_h)
        if bad_h:
            dq.reject("T02", "timesheets", r); continue
        out_of_range = h <= 0 or h > MAX_DAILY_HOURS
        dq.hit("T03", out_of_range)
        if out_of_range:
            dq.reject("T03", "timesheets", r); continue
        dq.hit("T04", eid not in emp_lookup)
        if eid not in emp_lookup:
            dq.reject("T04", "timesheets", r); continue
        dq.hit("T05", pid not in project_ids)
        if pid not in project_ids:
            dq.reject("T05", "timesheets", r); continue
        bad_date = d is None or d > AS_OF
        dq.hit("T06", bad_date)
        if bad_date:
            dq.reject("T06", "timesheets", r); continue
        pre_hire = find_version(emp_lookup, eid, d) is None
        dq.hit("T07", pre_hire)
        if pre_hire:
            dq.reject("T07", "timesheets", r); continue
        flag = r["billable_flag"].strip()
        dq.hit("T09", flag not in ("Y", "N"))
        out.append({"timesheet_id": tid, "employee_id": eid, "project_id": pid, "work_date": d, "hours": h,
                    "is_billable": flag.upper() in TRUE_FLAGS})
    return out


def parse_amount(s):
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None


def clean_invoices(raw, project_client, dq: DQ):
    seen, out = set(), []
    for r in raw:
        iid = r["invoice_id"].strip()
        dup = iid in seen
        dq.hit("I01", dup)
        if dup:
            continue
        seen.add(iid)
        pid = norm_id(r["project_id"])
        dq.hit("I07", pid not in project_client)
        if pid not in project_client:
            dq.reject("I07", "invoices", r); continue
        cid = norm_id(r["client_id"])
        dq.hit("I02", cid == "")
        cid = cid or project_client[pid]
        dq.hit("I03", cid != project_client[pid])
        if cid != project_client[pid]:
            dq.reject("I03", "invoices", r); continue
        dq.hit("I04", "," in r["amount"])
        amt = parse_amount(r["amount"])
        dq.hit("I06", amt is None or amt <= 0)
        if amt is None or amt <= 0:
            dq.reject("I06", "invoices", r); continue
        idate, _ = parse_date(r["invoice_date"])
        due, _ = parse_date(r["due_date"])
        bad = idate is None or due is None or due < idate
        dq.hit("I05", bad)
        if bad:
            dq.reject("I05", "invoices", r); continue
        out.append({"invoice_id": iid, "project_id": pid, "client_id": cid, "billing_period": r["billing_period"].strip(),
                    "invoice_date": idate, "due_date": due, "amount": amt})
    return out


def clean_payments(raw, invoices_by_id, dq: DQ):
    seen, out = set(), []
    for r in raw:
        pid = r["payment_id"].strip()
        dup = pid in seen
        dq.hit("Y01", dup)
        if dup:
            continue
        seen.add(pid)
        iid = r["invoice_id"].strip()
        dq.hit("Y02", iid not in invoices_by_id)
        if iid not in invoices_by_id:
            dq.reject("Y02", "payments", r); continue
        amt = parse_amount(r["amount"])
        dq.hit("Y03", amt is None or amt <= 0)
        if amt is None or amt <= 0:
            dq.reject("Y03", "payments", r); continue
        d, _ = parse_date(r["paid_date"])
        bad = d is None or d > AS_OF or d < invoices_by_id[iid]["invoice_date"]
        dq.hit("Y04", bad)
        if bad:
            dq.reject("Y04", "payments", r); continue
        out.append({"payment_id": pid, "invoice_id": iid, "paid_date": d, "amount": amt, "method": r["method"].strip()})
    return out
