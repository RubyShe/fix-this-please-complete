#!/usr/bin/env python3
"""
Step 02 (v1.0): the four per-task RQ2 metrics, one row per agent task.

For every task we compute:
  1. human_iterations: the number of sessions in the task, minus one
  2. cost in credits: see the note below
  3. merge status: merged, closed_no_merge, open, or no_pr (from pull_requests)
  4. change size: added plus deleted lines, and files changed (from pull_requests)

A note on credits. The data mixes two billing units. Each session has a
premium_requests field and a usage struct {type, amount, credits}:
  - usage.type = premium_requests: premium_requests is the credit cost, cleanly.
  - usage.type = ai_credits: custom or bring-your-own models. Here premium_requests is
    0 and usage.amount is a large, token-like count. GitHub publishes no
    token-to-credit rate for these, so their credit cost is ambiguous.

So we report a sensitivity range, as the paper describes:
    cost_floor: the sum of premium_requests (custom sessions count as 0, a lower bound)
    cost_mid:   the floor, but each custom session gets the per-model median
                premium_requests of that model's normally billed sessions (the rate is
                inferred from the data, with the global median as a fallback)
    cost_high:  the same, at the per-model 90th percentile (a plausible upper bound)

We also keep, per task: custom_credits_raw (the summed ai_credits usage.amount,
reported alongside), n_custom_sessions, and n_nousage_sessions (sessions with usage
missing, a data gap). cost_credits is an alias of cost_floor, kept for backward
compatibility.

Output: outputs/rq2_task_metrics_v1.0.parquet (and .csv), one row per task.
"""
from __future__ import annotations
from pathlib import Path
import duckdb

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
D = PROJECT / "data" / "dataset_v1.0"
OUT = PROJECT / "outputs"; OUT.mkdir(exist_ok=True)

S  = f"read_parquet('{D}/agent_sessions/*.parquet')"
T  = f"read_parquet('{D}/agent_tasks/*.parquet')"
PR = f"read_parquet('{D}/pull_requests/*.parquet')"
CLS = f"read_parquet('{PROJECT}/data/session_classifications.parquet')"

con = duckdb.connect()

# ---- per-model credit rate, learned from NORMALLY-billed sessions ----
con.execute(f"""
CREATE TEMP TABLE model_rate AS
SELECT model,
       median(premium_requests)              AS p50,
       quantile_cont(premium_requests, 0.90) AS p90
FROM {S}
WHERE usage.type = 'premium_requests' AND premium_requests IS NOT NULL
GROUP BY model;
""")
con.execute(f"""
CREATE TEMP TABLE gl AS
SELECT median(premium_requests) AS p50, quantile_cont(premium_requests,0.90) AS p90
FROM {S} WHERE usage.type = 'premium_requests' AND premium_requests IS NOT NULL;
""")

# ---- per-task session rollup: iterations + cost (floor / mid / high) ----
con.execute(f"""
CREATE TEMP TABLE task_sessions AS
SELECT s.task.id AS task_id,
  count(*)        AS n_sessions,
  count(*) - 1    AS human_iterations,
  -- developer rounds: later sessions with developer-written text (exclude auto re-runs,
  -- which the classifier marks type='missing'); aligns with the RQ3 round definition
  sum((s.session_index >= 1 AND cl.type IN ('prompt','direct'))::int) AS developer_rounds,
  -- floor: recorded credits; custom (ai_credits) sessions are 0
  sum(coalesce(s.premium_requests, 0))                                   AS cost_floor,
  -- mid: impute custom sessions at per-model median (fallback: global median)
  sum(CASE WHEN s.usage.type = 'ai_credits'
           THEN coalesce(mr.p50, gl.p50)
           ELSE coalesce(s.premium_requests, 0) END)                     AS cost_mid,
  -- high: impute custom sessions at per-model 90th pct (fallback: global 90th)
  sum(CASE WHEN s.usage.type = 'ai_credits'
           THEN coalesce(mr.p90, gl.p90)
           ELSE coalesce(s.premium_requests, 0) END)                     AS cost_high,
  -- raw custom usage (token-like ai_credits amount), reported alongside
  sum(CASE WHEN s.usage.type = 'ai_credits' THEN coalesce(s.usage.amount,0) ELSE 0 END) AS custom_credits_raw,
  sum((s.usage.type = 'ai_credits')::int)  AS n_custom_sessions,
  sum((s.usage.type IS NULL)::int)         AS n_nousage_sessions
FROM {S} s
LEFT JOIN model_rate mr ON mr.model = s.model
LEFT JOIN {CLS} cl ON cl.session_id = s.id
CROSS JOIN gl
GROUP BY 1;
""")

# ---- PR -> task (a PR may list several creating tasks; explode) ----
con.execute(f"""
CREATE TEMP TABLE task_pr AS
SELECT ct.id AS task_id,
       p.number, p.state, p.merged, p.merged_at, p.closed_at,
       p.additions_count, p.deletions_count, p.changed_files_count,
       (coalesce(p.additions_count,0) + coalesce(p.deletions_count,0)) AS lines_changed
FROM {PR} p, UNNEST(p.created_by_tasks) AS u(ct)
WHERE ct.id IS NOT NULL;
""")
con.execute("""
CREATE TEMP TABLE task_pr1 AS
SELECT * FROM (
  SELECT *, row_number() OVER (
      PARTITION BY task_id
      ORDER BY (merged IS TRUE) DESC, lines_changed DESC NULLS LAST
  ) AS rn FROM task_pr
) WHERE rn = 1;
""")

# ---- join: one row per task ----
con.execute("""
CREATE TEMP TABLE rq2 AS
SELECT
  ts.task_id, ts.n_sessions, ts.human_iterations, ts.developer_rounds,
  ts.cost_floor AS cost_credits,          -- backward-compatible primary (= floor)
  ts.cost_floor, ts.cost_mid, ts.cost_high,
  ts.custom_credits_raw, ts.n_custom_sessions, ts.n_nousage_sessions,
  (ts.n_custom_sessions > 0) AS has_custom_billing,
  (p.number IS NOT NULL)     AS has_pr,
  p.number AS pr_number, p.state AS pr_state, p.merged AS pr_merged,
  CASE
    WHEN p.number IS NULL  THEN 'no_pr'
    WHEN p.merged IS TRUE  THEN 'merged'
    WHEN p.state = 'open'  THEN 'open'
    ELSE 'closed_no_merge'
  END AS merge_status,
  p.additions_count, p.deletions_count, p.lines_changed, p.changed_files_count
FROM task_sessions ts
LEFT JOIN task_pr1 p USING (task_id);
""")

n = con.sql("SELECT count(*) FROM rq2").fetchone()[0]
con.execute(f"COPY rq2 TO '{OUT}/rq2_task_metrics_v1.0.parquet' (FORMAT PARQUET)")
con.execute(f"COPY rq2 TO '{OUT}/rq2_task_metrics_v1.0.csv' (HEADER, DELIMITER ',')")
print(f"[done] {n:,} tasks -> outputs/rq2_task_metrics_v1.0.parquet (+ .csv)\n")

print("=== cost sensitivity: population medians (floor / mid / high) ===")
print(con.sql("""SELECT median(cost_floor) med_floor, median(cost_mid) med_mid, median(cost_high) med_high,
  round(avg(cost_floor),2) mean_floor, round(avg(cost_mid),2) mean_mid, round(avg(cost_high),2) mean_high
  FROM rq2""").df().to_string(index=False))
print("\n=== how many tasks are affected by custom billing? ===")
print(con.sql("""SELECT sum(has_custom_billing::int) tasks_with_custom,
  round(100.0*sum(has_custom_billing::int)/count(*),1) pct,
  sum((n_nousage_sessions>0)::int) tasks_with_nousage_sessions FROM rq2""").df().to_string(index=False))
print("\n=== merge_status distribution (unchanged) ===")
print(con.sql("SELECT merge_status, count(*) c FROM rq2 GROUP BY 1 ORDER BY c DESC").df().to_string(index=False))
