"""Generate a messy extract from a fictional consulting firm's source systems.

Six CSV files are written to data/raw, the way HR, project, timesheet, billing and
bank-receipts systems would hand them over. Realistic defects are injected on purpose
(duplicates, blanks, bad dates, orphan keys, inconsistent codes) so the pipeline has real
cleaning and data-quality work to do. All data is synthetic.
"""
import csv
import datetime as dt
import random
from collections import defaultdict
from pathlib import Path

from .config import AS_OF, SEED, WINDOW_START

FIRST = ["Aarav", "Ananya", "Vihaan", "Diya", "Rohan", "Meera", "Karthik", "Sneha", "Arjun", "Priya", "Rahul", "Kavya",
         "Nikhil", "Ishita", "Sanjay", "Divya", "Varun", "Neha", "Manoj", "Lakshmi", "Harsha", "Pooja", "Suresh",
         "Anjali", "Naveen", "Swathi", "Vamsi", "Bhavana", "Teja", "Shreya"]
LAST = ["Reddy", "Sharma", "Rao", "Iyer", "Nair", "Gupta", "Patel", "Kumar", "Naidu", "Verma", "Singh", "Joshi",
        "Mehta", "Das", "Chowdary"]
PRACTICES = ["Data & Analytics", "Risk Advisory", "Finance Transformation", "Tax Technology"]
LOCATIONS = ["Hyderabad", "Bengaluru", "Mumbai", "Delhi NCR"]
# grade, bill rate (INR/hour), cost rate (INR/hour)
GRADES = [("Analyst", 1800, 650), ("Senior Analyst", 2600, 950), ("Consultant", 3600, 1300),
          ("Manager", 5200, 1900), ("Director", 8000, 2900)]
GRADE_WEIGHTS = [28, 30, 22, 14, 6]
CLIENTS = [
    ("Orion Steel", "Manufacturing"), ("BlueLeaf Pharma", "Healthcare"), ("Sapphire Retail", "Retail"),
    ("Nimbus Cloud", "Technology"), ("Kestrel Logistics", "Logistics"), ("Lumen Hospitals", "Healthcare"),
    ("Vertex Auto", "Manufacturing"), ("Pioneer Foods", "Consumer Goods"), ("Zenith Power", "Utilities"),
    ("Harbor Textiles", "Manufacturing"), ("Cedar Bank", "Banking"), ("Atlas Insurance", "Insurance"),
    ("Maple Telecom", "Telecom"), ("Quartz Mining", "Mining"), ("Helix Biotech", "Healthcare"),
    ("Summit Realty", "Real Estate"), ("Falcon Airways", "Aviation"), ("Indigo Fintech", "Banking"),
    ("Coral Hotels", "Hospitality"), ("Granite Cement", "Manufacturing"), ("Aurora Solar", "Utilities"),
    ("Nova Pharma", "Healthcare"), ("Tidal Shipping", "Logistics"), ("Ember Energy", "Utilities"),
    ("Willow Education", "Education"), ("Cobalt Electronics", "Technology"), ("Saffron Foods", "Consumer Goods"),
    ("Pinnacle Finance", "Banking"), ("Terra Agro", "Agriculture"), ("Lotus Healthcare", "Healthcare")]
CITIES = ["Hyderabad", "Mumbai", "Chennai", "Pune", "Bengaluru", "Delhi", "Kolkata", "Ahmedabad"]
METHODS = ["NEFT", "RTGS", "UPI", "Cheque"]


def _fmt_date(d: dt.date, rnd: random.Random, mixed: float = 0.12) -> str:
    """Most systems export ISO dates; one legacy system exports dd/mm/yyyy."""
    return d.strftime("%d/%m/%Y") if rnd.random() < mixed else d.isoformat()


def _write(path: Path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def generate(raw_dir: Path, seed: int = SEED) -> dict:
    rnd = random.Random(seed)
    raw_dir = Path(raw_dir)

    # ---------------- rate card, employees, grade history ----------------
    rate_card = [(g, b, c) for g, b, c in GRADES]
    employees, history = [], []
    for i in range(1, 61):
        eid = f"E{i:03d}"
        hire = dt.date(2023, 1, 1) + dt.timedelta(days=rnd.randint(0, 1185))
        g = rnd.choices(range(5), GRADE_WEIGHTS)[0]
        name = f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"
        employees.append({"employee_id": eid, "full_name": name, "practice": rnd.choice(PRACTICES),
                          "location": rnd.choice(LOCATIONS), "hire_date": hire,
                          "email": f"{name.lower().replace(' ', '.')}.{i}@meridian-advisory.example"})
        history.append((eid, GRADES[g][0], hire))
        if g < 4 and rnd.random() < 0.45:
            promo = hire + dt.timedelta(days=rnd.randint(200, 700))
            if promo < AS_OF:
                history.append((eid, GRADES[g + 1][0], promo))
    hist_by_emp = defaultdict(list)
    for eid, grade, eff in history:
        hist_by_emp[eid].append((eff, grade))
    for v in hist_by_emp.values():
        v.sort()
    rates = {g: (b, c) for g, b, c in GRADES}

    def bill_rate(eid, d):
        grade = [g for eff, g in hist_by_emp[eid] if eff <= d][-1]
        return rates[grade][0]

    # ---------------- clients ----------------
    clients = []
    for i, (name, ind) in enumerate(CLIENTS, 1):
        clients.append({"client_id": f"C{i:03d}", "client_name": name, "industry": ind,
                        "city": rnd.choice(CITIES), "payment_terms_days": rnd.choice([30, 45, 60]),
                        "tier": rnd.choices(["Strategic", "Key", "Standard"], [15, 35, 50])[0]})
    # behaviour used later when payments are simulated
    slow = set(rnd.sample([c["client_id"] for c in clients], 3))
    delay_mean = {c["client_id"]: (rnd.uniform(55, 70) if c["client_id"] in slow else rnd.uniform(-3, 35))
                  for c in clients}

    # ---------------- projects and timesheets (ground truth) ----------------
    projects, truth_ts = [], []
    by_practice = defaultdict(list)
    for e in employees:
        by_practice[e["practice"]].append(e)
    ts_n = 0
    day_hours = defaultdict(float)     # nobody works 25 hours in a day: cap total logged hours per person per day
    for i in range(1, 81):
        pid = f"P{i:03d}"
        client = rnd.choice(clients)
        practice = rnd.choice(PRACTICES)
        start = WINDOW_START + dt.timedelta(days=rnd.randint(0, 600))
        end = start + dt.timedelta(days=rnd.randint(90, 420))
        pool = [e for e in by_practice[practice] if e["hire_date"] <= start + dt.timedelta(days=30)]
        pool += [e for e in employees if e["practice"] != practice and e["hire_date"] <= start
                 and rnd.random() < 0.25]
        if len(pool) < 3:
            pool = [e for e in employees if e["hire_date"] <= start + dt.timedelta(days=60)]
        team = rnd.sample(pool, min(len(pool), rnd.randint(3, 6)))
        total = 0.0
        d = start
        while d <= min(end, AS_OF):
            if d.weekday() < 5:
                for e in team:
                    if d >= e["hire_date"] and rnd.random() < 0.5:
                        h = rnd.choice([2, 3, 4, 4.5, 5, 6, 6, 7, 8])
                        if day_hours[(e["employee_id"], d)] + h > 10:
                            continue
                        day_hours[(e["employee_id"], d)] += h
                        ts_n += 1
                        truth_ts.append({"ts_id": f"TS{ts_n:06d}", "employee_id": e["employee_id"],
                                         "project_id": pid, "work_date": d, "hours": h,
                                         "billable": rnd.random() < 0.92})
                        total += h
            d += dt.timedelta(days=1)
        projects.append({"project_id": pid, "client_id": client["client_id"],
                         "project_name": f"{client['client_name']} {rnd.choice(['Data Platform', 'Controls Review', 'ERP Migration', 'Reporting Revamp', 'Risk Assessment', 'Tax Automation', 'Audit Analytics'])}",
                         "practice": practice, "billing_type": rnd.choice(["Time & Materials", "Fixed Fee"]),
                         "start_date": start, "end_date": end,
                         "budget_hours": round(total * rnd.uniform(0.85, 1.3))})
    proj_client = {p["project_id"]: p["client_id"] for p in projects}
    terms = {c["client_id"]: c["payment_terms_days"] for c in clients}

    # ---------------- invoices and payments (ground truth) ----------------
    value = defaultdict(float)
    for t in truth_ts:
        if t["billable"]:
            value[(t["project_id"], t["work_date"].strftime("%Y-%m"))] += t["hours"] * bill_rate(t["employee_id"], t["work_date"])
    invoices, payments = [], []
    inv_n = pay_n = 0
    for (pid, period), v in sorted(value.items(), key=lambda x: (x[0][1], x[0][0])):
        y, m = map(int, period.split("-"))
        month_end = (dt.date(y + (m == 12), (m % 12) + 1, 1) - dt.timedelta(days=1))
        inv_date = month_end + dt.timedelta(days=rnd.randint(3, 8))
        if inv_date > AS_OF:
            continue                                  # still unbilled work in progress
        cid = proj_client[pid]
        realization = min(1.03, max(0.75, rnd.gauss(0.93, 0.06)))
        amount = round(v * realization)
        inv_n += 1
        inv_id = f"INV-{inv_n:05d}"
        due = inv_date + dt.timedelta(days=terms[cid])
        invoices.append({"invoice_id": inv_id, "project_id": pid, "client_id": cid, "billing_period": period,
                         "invoice_date": inv_date, "due_date": due, "amount": amount})
        if rnd.random() < 0.02:
            continue                                  # disputed, never paid
        pay_date = due + dt.timedelta(days=round(rnd.gauss(delay_mean[cid], 8)))
        pay_date = max(pay_date, inv_date + dt.timedelta(days=2))
        if rnd.random() < 0.08:                       # partial payment in two instalments
            first = round(amount * 0.6)
            for dte, amt in ((pay_date, first), (pay_date + dt.timedelta(days=rnd.randint(15, 45)), amount - first)):
                if dte <= AS_OF:
                    pay_n += 1
                    payments.append({"payment_id": f"PAY-{pay_n:05d}", "invoice_id": inv_id, "paid_date": dte,
                                     "amount": amt, "method": rnd.choice(METHODS)})
        elif pay_date <= AS_OF:
            pay_n += 1
            payments.append({"payment_id": f"PAY-{pay_n:05d}", "invoice_id": inv_id, "paid_date": pay_date,
                             "amount": amount, "method": rnd.choice(METHODS)})

    stats = {}

    # ---------------- inject defects ----------------
    # clients
    rows = []
    for c in clients:
        ind = c["industry"]
        r = rnd.random()
        ind = ind.upper() if r < 0.08 else ind.lower() if r < 0.16 else ind
        rows.append([c["client_id"], c["client_name"], ind, c["city"], c["payment_terms_days"], c["tier"]])
    for idx in rnd.sample(range(len(rows)), 2):
        rows[idx][2] = ""                              # missing industry
    for idx in rnd.sample(range(len(rows)), 2):        # duplicate client with sloppy spelling
        dup = list(rows[idx]); dup[1] = dup[1] + " "
        rows.append(dup)
    _write(raw_dir / "clients.csv", ["client_id", "client_name", "industry", "city", "payment_terms_days", "tier"], rows)
    stats["clients"] = len(rows)

    # projects
    rows = [[p["project_id"], p["client_id"], p["project_name"], p["practice"], p["billing_type"],
             _fmt_date(p["start_date"], rnd), _fmt_date(p["end_date"], rnd), p["budget_hours"]] for p in projects]
    _write(raw_dir / "projects.csv", ["project_id", "client_id", "project_name", "practice", "billing_type",
                                      "start_date", "end_date", "budget_hours"], rows)
    stats["projects"] = len(rows)

    # employees and history
    _write(raw_dir / "employees.csv", ["employee_id", "full_name", "practice", "location", "hire_date", "email"],
           [[e["employee_id"], e["full_name"], e["practice"], e["location"], _fmt_date(e["hire_date"], rnd), e["email"]]
            for e in employees])
    _write(raw_dir / "employee_grade_history.csv", ["employee_id", "grade", "effective_date"],
           [[a, b, _fmt_date(c, rnd)] for a, b, c in history])
    _write(raw_dir / "rate_card.csv", ["grade", "bill_rate", "cost_rate"], rate_card)
    stats["employees"] = len(employees)

    # timesheets
    hire = {e["employee_id"]: e["hire_date"] for e in employees}
    Y = ["Y", "Y", "Y", "y", "Yes", "TRUE", "1"]
    N = ["N", "N", "n", "No", "FALSE", "0"]
    rows = []
    for t in truth_ts:
        eid, pid, d, h = t["employee_id"], t["project_id"], t["work_date"], str(t["hours"])
        flag = rnd.choice(Y if t["billable"] else N)
        r = rnd.random()
        if r < 0.004:
            h = ""
        elif r < 0.010:
            h = rnd.choice(["-4", "0", "80", "99"])
        r = rnd.random()
        if r < 0.005:
            eid = "E999"
        elif r < 0.009:
            pid = "P999"
        elif r < 0.012:
            d = AS_OF + dt.timedelta(days=20)
        elif r < 0.014:
            d = hire[eid] - dt.timedelta(days=30)
        if rnd.random() < 0.010:
            eid = eid.lower()
        if rnd.random() < 0.010:
            pid = pid + " "
        rows.append([t["ts_id"], eid, pid, _fmt_date(d, rnd), h, flag])
    dups = rnd.sample(rows, round(len(rows) * 0.012))
    rows += [list(r) for r in dups]
    rnd.shuffle(rows)
    _write(raw_dir / "timesheets.csv", ["timesheet_id", "employee_id", "project_id", "work_date", "hours", "billable_flag"], rows)
    stats["timesheets"] = len(rows)

    # invoices
    rows = []
    for inv in invoices:
        cid, amt, due = inv["client_id"], str(inv["amount"]), inv["due_date"]
        if rnd.random() < 0.006:
            cid = ""                                   # recoverable from the project
        if rnd.random() < 0.02:                        # Indian digit grouping exported as text
            s = str(inv["amount"]); head, tail = s[:-3], s[-3:]
            parts = []
            while len(head) > 2:
                parts.insert(0, head[-2:]); head = head[:-2]
            if head:
                parts.insert(0, head)
            amt = ",".join(parts + [tail])
        if rnd.random() < 0.004:
            due = inv["invoice_date"] - dt.timedelta(days=10)
        rows.append([inv["invoice_id"], inv["project_id"], cid, inv["billing_period"],
                     _fmt_date(inv["invoice_date"], rnd, 0.10), _fmt_date(due, rnd, 0.10), amt])
    rows += [list(r) for r in rnd.sample(rows, round(len(rows) * 0.01))]
    rnd.shuffle(rows)
    _write(raw_dir / "invoices.csv", ["invoice_id", "project_id", "client_id", "billing_period", "invoice_date",
                                      "due_date", "amount"], rows)
    stats["invoices"] = len(rows)

    # payments
    rows = [[p["payment_id"], p["invoice_id"], _fmt_date(p["paid_date"], rnd), p["amount"], p["method"]] for p in payments]
    for k in range(max(1, round(len(rows) * 0.005))):
        rows.append([f"PAY-9{k:04d}", "INV-99999", AS_OF.isoformat(), 100000, "NEFT"])   # unknown invoice
    rows += [list(r) for r in rnd.sample(rows, round(len(rows) * 0.01))]
    rnd.shuffle(rows)
    _write(raw_dir / "payments.csv", ["payment_id", "invoice_id", "paid_date", "amount", "method"], rows)
    stats["payments"] = len(rows)
    return stats


if __name__ == "__main__":
    from .config import default_paths
    print(generate(default_paths().raw))
