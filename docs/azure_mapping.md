# Mapping this project to Azure

**This is a design note. Nothing in this repository has been deployed to Azure.** It shows how each stage here corresponds to a service in the Microsoft data stack, so the same logic could be moved there.

| Stage in this repo | What it does | Azure equivalent |
|---|---|---|
| `data/raw/*.csv` | Files handed over by source systems | Azure Data Lake Storage Gen2, a `raw` container with one folder per source and a date partition |
| `etl/pipeline.py` | Orchestrates steps, logs progress, fails on critical checks | Azure Data Factory pipeline with activities per step, triggered on a schedule, with failure alerts |
| `etl/transform.py` | Cleaning, standardising, quarantining | Mapping Data Flows, or Databricks / Synapse Spark notebooks for larger volumes |
| `etl/load.py` and `sql/01_schema.sql` | Loads a star schema | Azure SQL Database or a Synapse dedicated SQL pool, loaded with the Copy activity or `COPY INTO` |
| SCD type 2 in `build_employee_versions` | Keeps history of grade changes | A `MERGE` statement in a stored procedure, or the Data Flow "Alter row" with a Type 2 pattern |
| `sql/02_views.sql` | Reporting layer | Views in the warehouse, one semantic layer for every report |
| `etl/checks.py` and `dq_*` tables | Reconciliation and rule results | Pipeline validation activities, plus a data-quality table surfaced in Power BI. Microsoft Purview adds cataloguing and lineage. |
| `output/marts` and `powerbi/` | Reporting extracts | Power BI semantic model in Import or DirectQuery mode on the warehouse |
| `.github/workflows/ci.yml` | Runs the pipeline and tests on every change | Azure DevOps or GitHub Actions deploying ADF and SQL objects |

## Design choices that carry over unchanged

- **Land data raw, never edit it.** The raw layer stays as received so any load can be replayed.
- **Quarantine, do not drop.** Rejected rows keep their rule id so a data owner can fix them at source.
- **Reconcile every load.** Rows in must equal rows loaded plus rows rejected plus duplicates removed.
- **Keep business logic in views or procedures,** not inside the report, so Power BI and any other tool agree.
- **Parameterise the reporting date** so numbers are reproducible.
