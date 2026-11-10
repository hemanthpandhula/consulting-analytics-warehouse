"""Run with:  python -m unittest discover -s tests -v

The pipeline is executed once into a temporary folder; the tests then check reconciliation,
integrity, slowly-changing-dimension behaviour, report logic and the helper functions.
"""
import datetime as dt
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.config import AS_OF, Paths  # noqa: E402
from etl.pipeline import run  # noqa: E402
from etl import transform as T  # noqa: E402


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.paths = Paths(Path(cls.tmp.name))
        cls.summary = run(cls.paths, regenerate=True)
        cls.con = sqlite3.connect(cls.paths.db)

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        cls.tmp.cleanup()

    def q(self, sql):
        return self.con.execute(sql).fetchall()

    # ---- reconciliation ----
    def test_no_critical_failures(self):
        self.assertEqual(self.summary["critical_failures"], [])

    def test_every_raw_row_is_accounted_for(self):
        s = self.summary
        for t, n in s["raw_rows"].items():
            self.assertEqual(n, s["loaded_rows"][t] + s["duplicates_removed"][t] + s["quarantined"][t], t)

    def test_defects_were_actually_found(self):
        # the pipeline must be doing real work on the injected defects
        self.assertGreater(self.summary["duplicates_removed"]["timesheets"], 100)
        self.assertGreater(self.summary["quarantined"]["timesheets"], 100)
        self.assertGreater(self.q("SELECT COUNT(*) FROM dq_quarantine")[0][0], 0)

    # ---- integrity ----
    def test_foreign_keys_are_valid(self):
        self.assertEqual(self.q("PRAGMA foreign_key_check"), [])

    def test_no_duplicate_business_keys(self):
        self.assertEqual(self.q("SELECT COUNT(*) FROM (SELECT timesheet_id FROM fact_timesheet GROUP BY 1 HAVING COUNT(*)>1)")[0][0], 0)
        self.assertEqual(self.q("SELECT COUNT(*) FROM (SELECT invoice_id FROM fact_invoice GROUP BY 1 HAVING COUNT(*)>1)")[0][0], 0)

    def test_no_nulls_in_fact_keys(self):
        self.assertEqual(self.q("SELECT COUNT(*) FROM fact_invoice WHERE client_key IS NULL OR project_key IS NULL")[0][0], 0)

    # ---- slowly changing dimension ----
    def test_scd2_rate_matches_date_of_work(self):
        bad = self.q("""SELECT COUNT(*) FROM fact_timesheet f
                        JOIN dim_employee e ON e.employee_key = f.employee_key
                        JOIN dim_date d ON d.date_key = f.date_key
                        WHERE d.date < e.valid_from OR d.date >= e.valid_to""")[0][0]
        self.assertEqual(bad, 0)

    def test_promoted_employees_have_two_rates(self):
        rows = self.q("""SELECT employee_id, COUNT(DISTINCT bill_rate) FROM dim_employee
                         GROUP BY employee_id HAVING COUNT(*) > 1""")
        self.assertGreater(len(rows), 5)
        self.assertTrue(all(n == 2 for _, n in rows))

    def test_exactly_one_current_version_per_employee(self):
        self.assertEqual(self.q("SELECT COUNT(*) FROM (SELECT employee_id FROM dim_employee GROUP BY 1 HAVING SUM(is_current)<>1)")[0][0], 0)

    # ---- business logic ----
    def test_ageing_outstanding_ties_to_ledger(self):
        view = self.q("SELECT SUM(outstanding) FROM vw_ar_ageing")[0][0]
        ledger = self.q("""SELECT SUM(i.amount) - COALESCE((SELECT SUM(amount) FROM fact_payment), 0) FROM fact_invoice i""")[0][0]
        # the view drops invoices with <= 0.5 outstanding, so allow a tiny rounding difference
        self.assertAlmostEqual(view, ledger, delta=50)

    def test_utilization_is_plausible(self):
        lo, hi = self.q("SELECT MIN(utilization_pct), MAX(utilization_pct) FROM vw_utilization_monthly")[0]
        self.assertGreaterEqual(lo, 0)
        self.assertLess(hi, 130)

    def test_wip_only_contains_unbilled_periods(self):
        n = self.q("""SELECT COUNT(*) FROM vw_wip_unbilled w
                      JOIN dim_project p ON p.project_id = w.project_id
                      JOIN fact_invoice i ON i.project_key = p.project_key AND i.billing_period = w.period""")[0][0]
        self.assertEqual(n, 0)

    def test_all_analysis_queries_run(self):
        text = (self.paths.sql / "03_analysis_queries.sql").read_text()
        text = re.sub(r"--[^\n]*", "", text)
        statements = [s.strip() for s in text.split(";") if s.strip()]
        self.assertGreaterEqual(len(statements), 9)
        for s in statements:
            rows = self.con.execute(s).fetchall()
            self.assertGreater(len(rows), 0, s[:60])

    def test_marts_exported(self):
        for name in ("fact_timesheet", "vw_ar_ageing", "vw_project_profitability", "dim_employee"):
            self.assertTrue((self.paths.marts / f"{name}.csv").exists(), name)


class DeterminismTest(unittest.TestCase):
    def test_same_seed_same_result(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            sa, sb = run(Paths(Path(a))), run(Paths(Path(b)))
            sa.pop("seconds"); sb.pop("seconds")
            self.assertEqual(sa, sb)


class HelperTests(unittest.TestCase):
    def test_parse_date_handles_both_formats(self):
        self.assertEqual(T.parse_date("2026-01-31"), (dt.date(2026, 1, 31), True))
        self.assertEqual(T.parse_date("31/01/2026"), (dt.date(2026, 1, 31), False))
        self.assertEqual(T.parse_date("not a date"), (None, False))

    def test_parse_amount_handles_indian_grouping(self):
        self.assertEqual(T.parse_amount("1,23,456"), 123456.0)
        self.assertIsNone(T.parse_amount("abc"))

    def test_version_window_is_end_exclusive(self):
        v = [{"employee_id": "E1", "valid_from": dt.date(2025, 1, 1), "valid_to": dt.date(2025, 7, 1)},
             {"employee_id": "E1", "valid_from": dt.date(2025, 7, 1), "valid_to": dt.date(9999, 12, 31)}]
        lk = T.version_lookup(v)
        self.assertEqual(T.find_version(lk, "E1", dt.date(2025, 6, 30))["valid_to"], dt.date(2025, 7, 1))
        self.assertEqual(T.find_version(lk, "E1", dt.date(2025, 7, 1))["valid_from"], dt.date(2025, 7, 1))
        self.assertIsNone(T.find_version(lk, "E1", dt.date(2024, 12, 31)))

    def test_future_dated_timesheet_is_quarantined(self):
        from etl.quality import DQ
        dq = DQ(); T.define_rules(dq)
        v = [{"employee_id": "E1", "valid_from": dt.date(2025, 1, 1), "valid_to": dt.date(9999, 12, 31)}]
        row = {"timesheet_id": "TS1", "employee_id": "e1 ", "project_id": "P1", "work_date": (AS_OF + dt.timedelta(days=5)).isoformat(),
               "hours": "8", "billable_flag": "yes"}
        out = T.clean_timesheets([row], T.version_lookup(v), {"P1"}, dq)
        self.assertEqual(out, [])
        self.assertEqual(dq.quarantined("timesheets"), 1)

    def test_billable_flag_variants_are_standardised(self):
        from etl.quality import DQ
        dq = DQ(); T.define_rules(dq)
        v = [{"employee_id": "E1", "valid_from": dt.date(2025, 1, 1), "valid_to": dt.date(9999, 12, 31)}]
        rows = [{"timesheet_id": f"TS{i}", "employee_id": "E1", "project_id": "P1", "work_date": "2025-03-03",
                 "hours": "4", "billable_flag": f} for i, f in enumerate(["Y", "yes", "TRUE", "1", "N", "no", "0"])]
        out = T.clean_timesheets(rows, T.version_lookup(v), {"P1"}, dq)
        self.assertEqual([r["is_billable"] for r in out], [True, True, True, True, False, False, False])


if __name__ == "__main__":
    unittest.main()
