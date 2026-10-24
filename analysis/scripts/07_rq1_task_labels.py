#!/usr/bin/env python3
"""
Step 07 (v1.0): the per-task RQ1 label, which is the grouping key for RQ2 and RQ3.

For every task, take its first session (session_index = 0) and that session's published
intent classification. The task's ask type is the primary label (the first label, which
the classifier orders by dominance), rolled up to its main category. Tasks whose first
session is missing or error (no label) are dropped.

Output: sample/rq1_task_labels.csv (task_id, ask_type, ask_subtype), where
  ask_type is the main category, e.g. Code Authoring (the Table IV grouping)
  ask_subtype is the 14-label code, e.g. code_change
"""
from __future__ import annotations
import argparse, csv
from pathlib import Path
import duckdb

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
ap = argparse.ArgumentParser()
ap.add_argument("--dataset", default=str(PROJECT / "data" / "dataset_v1.0"))
ap.add_argument("--classifications", default=str(PROJECT / "data" / "session_classifications.parquet"))
ap.add_argument("--out", default=str(PROJECT / "sample" / "rq1_task_labels.csv"))
a = ap.parse_args()

SESS = f"read_parquet('{a.dataset}/agent_sessions/*.parquet')"
CLS = f"read_parquet('{a.classifications}')"

# label -> main category (adapted Tang codebook, 6 categories / 14 labels)
MAIN = {
 "code_creation": "Code Authoring", "code_change": "Code Authoring", "code_unspecified": "Code Authoring",
 "failure_log": "Failure Reporting", "failure_symptom": "Failure Reporting", "failure_unspecified": "Failure Reporting",
 "question_plan": "Inquiry", "question_project": "Inquiry", "question_general": "Inquiry",
 "review_code": "Validation", "review_runtime": "Validation",
 "documentation": "Delegation", "dev_operation": "Delegation",
 "other": "Others",
}

con = duckdb.connect()
con.create_function("to_main", lambda s: MAIN.get(s), ['VARCHAR'], 'VARCHAR')
rows = con.sql(f"""
SELECT s.task.id AS task_id,
       cl.labels[1] AS ask_subtype,
       to_main(cl.labels[1]) AS ask_type
FROM {SESS} s JOIN {CLS} cl ON cl.session_id = s.id
WHERE s.session_index = 0
  AND cl.type IN ('prompt','direct')
  AND cl.labels IS NOT NULL AND len(cl.labels) > 0
""").df()

Path(a.out).parent.mkdir(parents=True, exist_ok=True)
rows[["task_id","ask_type","ask_subtype"]].to_csv(a.out, index=False)
print(f"[done] {len(rows):,} labelled tasks -> {Path(a.out).relative_to(PROJECT)}")
print(rows["ask_type"].value_counts().to_string())
