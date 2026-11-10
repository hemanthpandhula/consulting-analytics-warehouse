"""Run the whole pipeline:  python run_pipeline.py [--keep-raw]

Generates the source extracts, cleans and validates them, loads the star schema into
output/warehouse.db, exports Power BI-ready marts, and writes the data-quality report.
Exit code is 1 if any critical check fails, so it can gate a scheduled job or CI run.
"""
import argparse
import sys

from etl.pipeline import run

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-raw", action="store_true", help="reuse data/raw instead of regenerating it")
    args = ap.parse_args()
    result = run(regenerate=not args.keep_raw)
    sys.exit(1 if result["critical_failures"] else 0)
